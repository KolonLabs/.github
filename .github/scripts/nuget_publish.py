from __future__ import annotations

import argparse
import copy
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from collections import deque
from dataclasses import dataclass
from typing import Dict, List

FEED_URL = "https://nuget.pkg.github.com/kolonlabs/index.json"
GITHUB_API_VERSION = "2022-11-28"
SEMVER_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-rc\.(\d+))?$")


@dataclass(frozen=True)
class ProjectInfo:
    package_id: str
    project_path: pathlib.Path
    version_prefix: str
    internal_dependencies: List[str]
    tag_prefix: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-type", required=True, choices=("rc", "stable"))
    parser.add_argument("--packages", default="")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--org", default="KolonLabs")
    return parser.parse_args()


def log(message: str) -> None:
    print(message, flush=True)


def fail(message: str) -> None:
    raise SystemExit(message)


def run_command(command: List[str], cwd: pathlib.Path, env: Dict[str, str] | None = None) -> str:
    log(f"> {' '.join(command)}")
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    return completed.stdout.strip()


def tag_name(tag_prefix: str, version: str) -> str:
    return f"{tag_prefix}{version}"


def parse_semver(version: str) -> tuple[int, int, int, int | None]:
    match = SEMVER_PATTERN.fullmatch(version)
    if not match:
        raise ValueError(f"Formato de version no soportado: {version}")
    major, minor, patch, rc = match.groups()
    return int(major), int(minor), int(patch), int(rc) if rc is not None else None


def version_sort_key(version: str) -> tuple[int, int, int, int, int]:
    major, minor, patch, rc = parse_semver(version)
    if rc is None:
        return major, minor, patch, 1, 0
    return major, minor, patch, 0, rc


def is_rc(version: str) -> bool:
    return parse_semver(version)[3] is not None


def find_text(root: ET.Element, local_name: str) -> str | None:
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] == local_name and element.text:
            return element.text.strip()
    return None


def namespace_prefix(tag: str) -> str:
    if tag.startswith("{"):
        return tag.split("}", 1)[0] + "}"
    return ""


def discover_projects(repo_root: pathlib.Path, selected_from_input: bool) -> Dict[str, ProjectInfo]:
    src_root = repo_root / "src"
    project_paths = sorted(src_root.rglob("*.csproj"))
    if not project_paths:
        fail("ERROR: No se encontro ningun .csproj bajo src")

    raw_data: List[tuple[str, pathlib.Path, str, List[pathlib.Path]]] = []
    package_ids: Dict[str, List[pathlib.Path]] = {}

    for project_path in project_paths:
        tree = ET.parse(project_path)
        root = tree.getroot()
        package_id = find_text(root, "PackageId") or project_path.stem
        version_prefix = find_text(root, "VersionPrefix")
        if not version_prefix:
            fail(f"ERROR: No se encontro <VersionPrefix> en {project_path.as_posix()}")

        dependency_paths: List[pathlib.Path] = []
        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1] != "ProjectReference":
                continue
            include = element.attrib.get("Include", "").strip()
            if not include:
                continue
            dependency_paths.append((project_path.parent / include).resolve())

        raw_data.append((package_id, project_path.resolve(), version_prefix, dependency_paths))
        package_ids.setdefault(package_id, []).append(project_path.resolve())

    duplicated_ids = {package_id: paths for package_id, paths in package_ids.items() if len(paths) > 1}
    if duplicated_ids:
        lines = ["ERROR: Hay multiples proyectos con el mismo PackageId. Corrigelos antes de publicar:"]
        for package_id, paths in sorted(duplicated_ids.items()):
            lines.append(f" - {package_id}: {', '.join(path.as_posix() for path in paths)}")
        fail("\n".join(lines))

    path_to_package = {project_path: package_id for package_id, project_path, _, _ in raw_data}
    implicit_single_package = len(raw_data) == 1 and not selected_from_input

    projects: Dict[str, ProjectInfo] = {}
    for package_id, project_path, version_prefix, dependency_paths in raw_data:
        internal_dependencies = [path_to_package[path] for path in dependency_paths if path in path_to_package]
        projects[package_id] = ProjectInfo(
            package_id=package_id,
            project_path=project_path,
            version_prefix=version_prefix,
            internal_dependencies=internal_dependencies,
            tag_prefix="v" if implicit_single_package else f"{package_id}-v",
        )

    return projects


def select_packages(projects: Dict[str, ProjectInfo], packages_raw: str) -> List[str]:
    if packages_raw.strip():
        requested = [item.strip() for item in packages_raw.split(",") if item.strip()]
        if not requested:
            fail("ERROR: El input 'packages' no contiene ningun PackageId valido.")
    elif len(projects) == 1:
        requested = [next(iter(projects))]
    else:
        lines = ["ERROR: Se encontraron multiples .csproj bajo src. Indica 'packages' para evitar ambiguedad."]
        for package_id in sorted(projects):
            lines.append(f" - {package_id}: {projects[package_id].project_path.as_posix()}")
        fail("\n".join(lines))

    selected: List[str] = []
    seen = set()
    for package_id in requested:
        if package_id not in projects:
            lines = [f"ERROR: No se encontro el paquete '{package_id}'.", "Paquetes disponibles:"]
            for available in sorted(projects):
                lines.append(f" - {available}")
            fail("\n".join(lines))
        if package_id not in seen:
            selected.append(package_id)
            seen.add(package_id)
    return selected


def topological_sort(selected: List[str], projects: Dict[str, ProjectInfo]) -> List[str]:
    selected_set = set(selected)
    indegree = {package_id: 0 for package_id in selected}
    graph = {package_id: [] for package_id in selected}

    for package_id in selected:
        for dependency in projects[package_id].internal_dependencies:
            if dependency not in selected_set:
                continue
            graph[dependency].append(package_id)
            indegree[package_id] += 1

    queue = deque(sorted([package_id for package_id, degree in indegree.items() if degree == 0]))
    ordered: List[str] = []

    while queue:
        package_id = queue.popleft()
        ordered.append(package_id)
        for dependant in sorted(graph[package_id]):
            indegree[dependant] -= 1
            if indegree[dependant] == 0:
                queue.append(dependant)

    if len(ordered) != len(selected):
        fail("ERROR: Se detecto un ciclo entre ProjectReference internos. No se puede publicar automaticamente.")

    return ordered


def git_tags(repo_root: pathlib.Path, pattern: str) -> List[str]:
    output = run_command(["git", "tag", "-l", pattern], cwd=repo_root)
    return [line.strip() for line in output.splitlines() if line.strip()]


def calculate_version(project: ProjectInfo, release_type: str, repo_root: pathlib.Path) -> tuple[str, str]:
    version_prefix = project.version_prefix
    if release_type == "stable":
        tag = tag_name(project.tag_prefix, version_prefix)
        if tag in git_tags(repo_root, tag):
            fail(f"ERROR: El tag {tag} ya existe. Actualiza <VersionPrefix> en {project.project_path.as_posix()}.")
        return version_prefix, tag

    existing_tags = git_tags(repo_root, f"{project.tag_prefix}{version_prefix}-rc.*")
    latest_rc = 0
    for existing in existing_tags:
        match = re.search(r"-rc\.(\d+)$", existing)
        if match:
            latest_rc = max(latest_rc, int(match.group(1)))
    version = f"{version_prefix}-rc.{latest_rc + 1}"
    return version, tag_name(project.tag_prefix, version)


def github_api_request(url: str, token: str) -> list[dict]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
            "User-Agent": "kolonlabs-nuget-workflow",
        },
    )
    try:
        with urllib.request.urlopen(request) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return []
        raise


def latest_published_version(package_id: str, release_type: str, org: str, token: str) -> str:
    encoded = urllib.parse.quote(package_id, safe="")
    versions: List[str] = []

    for page in range(1, 6):
        url = f"https://api.github.com/orgs/{org}/packages/nuget/{encoded}/versions?per_page=100&page={page}"
        batch = github_api_request(url, token)
        if not batch:
            break
        versions.extend(item.get("name", "").strip() for item in batch if item.get("name"))
        if len(batch) < 100:
            break

    parsed_versions = []
    for version in versions:
        try:
            parse_semver(version)
        except ValueError:
            continue
        parsed_versions.append(version)

    if not parsed_versions:
        fail(f"ERROR: No se encontraron versiones publicadas para {package_id} en GitHub Packages.")

    stable_versions = sorted([version for version in parsed_versions if not is_rc(version)], key=version_sort_key)
    rc_versions = sorted([version for version in parsed_versions if is_rc(version)], key=version_sort_key)

    if release_type == "stable":
        if not stable_versions:
            fail(f"ERROR: No existe ninguna version stable publicada para {package_id}.")
        return stable_versions[-1]

    if rc_versions:
        return rc_versions[-1]
    if stable_versions:
        log(f"Aviso: {package_id} no tiene RC publicada; se usara la ultima stable {stable_versions[-1]}.")
        return stable_versions[-1]

    fail(f"ERROR: No existe ninguna version publicada compatible para {package_id}.")


def resolve_dependency_versions(
    project: ProjectInfo,
    selected_versions: Dict[str, str],
    release_type: str,
    org: str,
    token: str,
    cache: Dict[str, str],
) -> Dict[str, str]:
    resolved: Dict[str, str] = {}
    for dependency in project.internal_dependencies:
        if dependency in selected_versions:
            resolved[dependency] = selected_versions[dependency]
            continue
        if dependency not in cache:
            cache[dependency] = latest_published_version(dependency, release_type, org, token)
        resolved[dependency] = cache[dependency]
    return resolved


def transform_project_file(
    project: ProjectInfo,
    dependency_versions: Dict[str, str],
    projects: Dict[str, ProjectInfo],
) -> pathlib.Path:
    temp_path = project.project_path.with_suffix(".publish.csproj")
    tree = ET.parse(project.project_path)
    root = tree.getroot()
    namespace = namespace_prefix(root.tag)

    property_groups = [element for element in root.iter() if element.tag.rsplit("}", 1)[-1] == "PropertyGroup"]
    package_id_element = None
    for property_group in property_groups:
        for child in property_group:
            if child.tag.rsplit("}", 1)[-1] == "PackageId":
                package_id_element = child
                break
        if package_id_element is not None:
            break

    if package_id_element is None:
        if property_groups:
            target_group = property_groups[0]
        else:
            target_group = ET.SubElement(root, f"{namespace}PropertyGroup")
        package_id_element = ET.SubElement(target_group, f"{namespace}PackageId")

    package_id_element.text = project.package_id

    path_to_package = {info.project_path.resolve(): package_id for package_id, info in projects.items()}

    for item_group in [element for element in root.iter() if element.tag.rsplit("}", 1)[-1] == "ItemGroup"]:
        children = list(item_group)
        replacements: List[tuple[int, ET.Element]] = []
        removals: List[ET.Element] = []
        for index, child in enumerate(children):
            if child.tag.rsplit("}", 1)[-1] != "ProjectReference":
                continue
            include = child.attrib.get("Include", "").strip()
            if not include:
                continue
            referenced_path = (project.project_path.parent / include).resolve()
            dependency = path_to_package.get(referenced_path)
            if dependency is None:
                continue
            version = dependency_versions.get(dependency)
            if version is None:
                continue
            package_reference = ET.Element(f"{namespace}PackageReference", {"Include": dependency, "Version": version})
            for metadata in child:
                metadata_name = metadata.tag.rsplit("}", 1)[-1]
                if metadata_name in {"IncludeAssets", "ExcludeAssets", "PrivateAssets"}:
                    package_reference.append(copy.deepcopy(metadata))
            replacements.append((index, package_reference))
            removals.append(child)

        for child in removals:
            item_group.remove(child)
        offset = 0
        for index, replacement in replacements:
            item_group.insert(index + offset, replacement)
            offset += 1

    if namespace.startswith("{"):
        ET.register_namespace("", namespace[1:-1])
    tree.write(temp_path, encoding="utf-8", xml_declaration=True)
    return temp_path


def find_created_package(output_dir: pathlib.Path) -> pathlib.Path:
    packages = sorted(path for path in output_dir.glob("*.nupkg") if not path.name.endswith(".symbols.nupkg"))
    if not packages:
        fail(f"ERROR: No se genero ningun paquete en {output_dir.as_posix()}")
    return packages[-1]


def cleanup_temp_file(path: pathlib.Path) -> None:
    if path.exists():
        path.unlink()


def create_tag(repo_root: pathlib.Path, tag: str) -> None:
    run_command(["git", "config", "user.name", "github-actions[bot]"], cwd=repo_root)
    run_command(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"], cwd=repo_root)
    run_command(["git", "tag", tag], cwd=repo_root)
    run_command(["git", "push", "origin", tag], cwd=repo_root)


def delete_tag(repo_root: pathlib.Path, tag: str) -> None:
    try:
        run_command(["git", "push", "origin", f":refs/tags/{tag}"], cwd=repo_root)
    finally:
        subprocess.run(["git", "tag", "-d", tag], cwd=str(repo_root), check=False, text=True, capture_output=True)


def create_release(repo_root: pathlib.Path, tag: str, release_type: str, env: Dict[str, str]) -> None:
    command = ["gh", "release", "create", tag, "--title", tag, "--generate-notes"]
    if release_type == "rc":
        command.append("--prerelease")
    run_command(command, cwd=repo_root, env=env)


def publish_package(
    project: ProjectInfo,
    version: str,
    tag: str,
    dependency_versions: Dict[str, str],
    projects: Dict[str, ProjectInfo],
    repo_root: pathlib.Path,
    release_type: str,
    local_feed_dir: pathlib.Path,
    runtime_env: Dict[str, str],
) -> None:
    log(f"\n=== Publicando {project.package_id} {version} ===")
    if dependency_versions:
        for dependency, dependency_version in sorted(dependency_versions.items()):
            log(f"Dependencia interna resuelta: {dependency} -> {dependency_version}")

    temp_project = transform_project_file(project, dependency_versions, projects)
    output_dir = repo_root / ".artifacts" / "nupkgs" / project.package_id
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        run_command(
            [
                "dotnet",
                "restore",
                temp_project.as_posix(),
                "--source",
                local_feed_dir.as_posix(),
                "--source",
                "https://api.nuget.org/v3/index.json",
                "--source",
                FEED_URL,
            ],
            cwd=repo_root,
            env=runtime_env,
        )
        run_command(
            [
                "dotnet",
                "pack",
                temp_project.as_posix(),
                "-c",
                "Release",
                "--no-restore",
                f"/p:Version={version}",
                "--output",
                output_dir.as_posix(),
            ],
            cwd=repo_root,
            env=runtime_env,
        )
        package_file = find_created_package(output_dir)
        shutil.copy2(package_file, local_feed_dir / package_file.name)
        run_command(
            [
                "dotnet",
                "nuget",
                "push",
                package_file.as_posix(),
                "--source",
                FEED_URL,
                "--api-key",
                runtime_env["KOLONLABS_NUGET_TOKEN"],
                "--skip-duplicate",
            ],
            cwd=repo_root,
            env=runtime_env,
        )
        create_tag(repo_root, tag)
        try:
            create_release(repo_root, tag, release_type, runtime_env)
        except subprocess.CalledProcessError:
            log(f"Fallo al crear la release {tag}. Eliminando el tag para evitar inconsistencias.")
            delete_tag(repo_root, tag)
            raise
    finally:
        cleanup_temp_file(temp_project)


def main() -> None:
    args = parse_args()
    repo_root = pathlib.Path(args.repo_root).resolve()
    token = os.environ.get("KOLONLABS_NUGET_TOKEN", "").strip()
    if not token:
        fail("ERROR: Falta la variable de entorno KOLONLABS_NUGET_TOKEN.")
    gh_token = os.environ.get("GH_TOKEN", "").strip()
    if not gh_token:
        fail("ERROR: Falta la variable de entorno GH_TOKEN.")

    selected_from_input = bool(args.packages.strip())
    projects = discover_projects(repo_root, selected_from_input)
    selected = select_packages(projects, args.packages)
    ordered = topological_sort(selected, projects)
    log("Orden de publicacion: " + " -> ".join(ordered))

    selected_versions: Dict[str, str] = {}
    selected_tags: Dict[str, str] = {}
    for package_id in ordered:
        version, tag = calculate_version(projects[package_id], args.release_type, repo_root)
        selected_versions[package_id] = version
        selected_tags[package_id] = tag
        log(f"Version calculada para {package_id}: {version} ({tag})")

    runtime_env = os.environ.copy()
    local_feed_dir = repo_root / ".artifacts" / "local-feed"
    if local_feed_dir.exists():
        shutil.rmtree(local_feed_dir)
    local_feed_dir.mkdir(parents=True, exist_ok=True)
    published_cache: Dict[str, str] = {}
    for package_id in ordered:
        project = projects[package_id]
        dependency_versions = resolve_dependency_versions(
            project=project,
            selected_versions=selected_versions,
            release_type=args.release_type,
            org=args.org,
            token=token,
            cache=published_cache,
        )
        publish_package(
            project=project,
            version=selected_versions[package_id],
            tag=selected_tags[package_id],
            dependency_versions=dependency_versions,
            projects=projects,
            repo_root=repo_root,
            release_type=args.release_type,
            local_feed_dir=local_feed_dir,
            runtime_env=runtime_env,
        )


if __name__ == "__main__":
    main()
