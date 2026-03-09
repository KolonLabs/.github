# NuGet · Publicación y Consumo

> Referencia para desarrolladores y pipelines CI/CD.
> Aplicable a cualquier repositorio de la organización KolonLabs que publique paquetes NuGet.

---

## Índice

- [1. Feed privado de la organización](#1-feed-privado-de-la-organización)
- [2. Configurar credenciales (PAT)](#2-configurar-credenciales-pat)
  - [2.1 Generar el PAT en GitHub](#21-generar-el-pat-en-github)
  - [2.2 Configurar las variables de entorno](#22-configurar-las-variables-de-entorno)
- [3. Flujo de versiones y publicación](#3-flujo-de-versiones-y-publicación)
  - [3.1 Durante desarrollo (sin publicar)](#31-durante-desarrollo-sin-publicar)
  - [3.2 Publicar una pre-release (RC)](#32-publicar-una-pre-release-rc)
  - [3.3 Publicar la versión estable](#33-publicar-la-versión-estable)
  - [3.4 Preparar la siguiente versión](#34-preparar-la-siguiente-versión)
  - [3.5 Repos con múltiples paquetes](#35-repos-con-múltiples-paquetes)
- [4. Consumir los paquetes](#4-consumir-los-paquetes)
  - [4.1 En desarrollo local](#41-en-desarrollo-local)
  - [4.2 En GitHub Actions (build / test / deploy)](#42-en-github-actions-build--test--deploy)
- [5. Referencia rápida de credenciales](#5-referencia-rápida-de-credenciales)
- [6. Configurar un nuevo repositorio SDK](#6-configurar-un-nuevo-repositorio-sdk)
  - [6.1 Repositorio con un solo paquete](#61-repositorio-con-un-solo-paquete)
  - [6.2 Repositorio con múltiples paquetes](#62-repositorio-con-múltiples-paquetes)
  - [6.3 nuget.config](#63-nugetconfig)
  - [6.4 Secret de organización `KOLONLABS_NUGET_TOKEN`](#64-secret-de-organización-kolonlabs_nuget_token)

---

## 1. Feed privado de la organización

Todos los paquetes `KL.*` se publican en GitHub Packages de la organización KolonLabs:

```
https://nuget.pkg.github.com/kolonlabs/index.json
```

Los paquetes disponibles en cada repositorio se listan en su propio `README.md`. Un repositorio puede publicar uno o múltiples paquetes:

| Paquete | Descripción |
|---|---|
| `KL.{Paquete1}` | _{descripción del paquete 1}_ |
| `KL.{Paquete2}` | _{descripción del paquete 2}_ |

---

## 2. Configurar credenciales (PAT)

GitHub Packages requiere autenticación tanto para publicar como para consumir paquetes.

### 2.1 Generar el PAT en GitHub

1. Accede a **GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)**
   Enlace directo: `https://github.com/settings/tokens/new`

2. Configura el token:
   - **Note:** nombre descriptivo, p.ej. `kolonlabs-nuget-local`
   - **Expiration:** según política del equipo (recomendado: 90 días)
   - **Scopes:**
     - `read:packages` — para consumir paquetes desde local

3. Haz clic en **Generate token** y copia el valor generado (`ghp_...`). Solo se muestra una vez.

> **Para el secret de organización usado en CI/CD:** el PAT que se configura como `KOLONLABS_NUGET_TOKEN` en la organización necesita `write:packages` (que incluye `read:packages`). Ver sección [6.4](#64-secret-de-organización-kolonlabs_nuget_token).

### 2.2 Configurar las variables de entorno

Establece la variable de entorno de forma **persistente** en tu máquina (nivel de usuario):

```powershell
# PowerShell — persiste entre sesiones (se guarda en el registro de Windows)
[System.Environment]::SetEnvironmentVariable("KOLONLABS_NUGET_TOKEN", "ghp_xxxxxxxxxxxxxxxxxxxx", "User")
```

> **Nota:** abre una terminal nueva tras ejecutar este comando para que la variable esté disponible.

Para verificar que está configurada:

```powershell
[System.Environment]::GetEnvironmentVariable("KOLONLABS_NUGET_TOKEN", "User")
```

Cuando el PAT expire, repite el proceso generando uno nuevo y ejecuta el comando de nuevo con el nuevo valor.

---

## 3. Flujo de versiones y publicación

La publicación se lanza **manualmente** desde GitHub Actions (`workflow_dispatch`). Un push normal a `main` nunca publica nada — solo ejecuta build y tests.

El workflow lee el `VersionPrefix` del `.csproj`, calcula la versión correspondiente, crea el tag en Git y publica el paquete.

### 3.1 Durante desarrollo (sin publicar)

Un push a `main` o la apertura de una PR dispara automáticamente el workflow — solo la fase **Build & Test**, sin publicar nada. No hay ningún comando adicional que lanzar:

```powershell
git add .
git commit -m "feat: descripción del cambio"
git push   # → GitHub Actions ejecuta build + test automáticamente
```

### 3.2 Publicar una pre-release (RC)

Cuando quieres que otros equipos prueben el trabajo en progreso, lanza el workflow indicando `rc`:

```powershell
# El workflow calcula automáticamente el número de RC consultando los tags existentes
gh workflow run publish.yml -f release_type=rc
```

El workflow:
1. Lee `VersionPrefix` del `.csproj` (ej: `0.2.0`)
2. Consulta los tags existentes para calcular el siguiente RC (ej: `v0.2.0-rc.1` si no hay ninguno, `v0.2.0-rc.2` si ya existe el primero)
3. Ejecuta `dotnet pack /p:Version=0.2.0-rc.1`
4. Crea el tag `v0.2.0-rc.1` en el repositorio
5. Publica el paquete en GitHub Packages
6. Crea una GitHub Release marcada como pre-release

> Los paquetes pre-release **no se instalan automáticamente** en proyectos consumidores al hacer `dotnet restore`. Deben referenciarse de forma explícita: `Version="0.2.0-rc.1"`. Esto garantiza que no rompen a nadie por defecto.

### 3.3 Publicar la versión estable

Cuando la versión está validada y lista para producción:

```powershell
gh workflow run publish.yml -f release_type=stable
```

El workflow verifica que no existe ya un tag `v{VersionPrefix}` y falla con un mensaje claro si lo hay — lo que indicaría que hay que actualizar el `VersionPrefix` antes de publicar.

### 3.4 Preparar la siguiente versión

Tras publicar la versión estable, actualiza el `VersionPrefix` en los `.csproj` para iniciar el siguiente ciclo:

```xml
<!-- src/KL.{Paquete1}/KL.{Paquete1}.csproj -->
<VersionPrefix>0.3.0</VersionPrefix>
```

```powershell
git add .
git commit -m "chore: bump version to 0.3.0"
git push
```

### 3.5 Repos con múltiples paquetes

Cuando un repositorio publica más de un paquete, cada uno tiene su propio `VersionPrefix` en su `.csproj`. El workflow acepta un parámetro adicional con el nombre del paquete a publicar:

```powershell
# Publicar solo KL.{Paquete1}
gh workflow run publish.yml -f release_type=stable -f package=KL.{Paquete1}

# Publicar solo KL.{Paquete2} como RC
gh workflow run publish.yml -f release_type=rc -f package=KL.{Paquete2}
```

El workflow localiza el `.csproj` del paquete indicado, lee su `VersionPrefix`, calcula la versión y publica únicamente ese paquete.

Los tags en repos multi-paquete incluyen el nombre del paquete como prefijo para evitar colisiones entre versiones de distintos paquetes: `KL.{Paquete1}-v0.2.0`, `KL.{Paquete2}-v1.0.0-rc.1`.

---

## 4. Consumir los paquetes

### 4.1 En desarrollo local

**1. `nuget.config` en la raíz del repositorio consumidor:**

```xml
<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <packageSources>
    <clear />
    <add key="NuGet official package source" value="https://api.nuget.org/v3/index.json" />
    <add key="KolonLabs" value="https://nuget.pkg.github.com/kolonlabs/index.json" />
  </packageSources>
  <packageSourceCredentials>
    <KolonLabs>
      <add key="Username" value="x" />
      <add key="ClearTextPassword" value="%KOLONLABS_NUGET_TOKEN%" />
    </KolonLabs>
  </packageSourceCredentials>
</configuration>
```

**2. Variable de entorno** configurada según la sección [2.2](#22-configurar-las-variables-de-entorno).

**3. Referencia en el `.csproj`:**

```xml
<!-- Versión estable -->
<PackageReference Include="KL.{Paquete1}" Version="0.2.0" />

<!-- Pre-release (explícito) -->
<PackageReference Include="KL.{Paquete1}" Version="0.2.0-rc.1" />
```

`dotnet restore` resolverá los paquetes automáticamente usando la variable de entorno.

---

### 4.2 En GitHub Actions (build / test / deploy)

> **Importante:** `GITHUB_TOKEN` en GitHub Actions solo tiene acceso a los paquetes publicados por el **propio repositorio**. Para consumir paquetes de otros repositorios de la organización (p.ej. `KL.Common` desde `sdk-common`), se obtiene un **403 Forbidden**. Es obligatorio usar el secret de organización `KOLONLABS_NUGET_TOKEN`.

El secret `KOLONLABS_NUGET_TOKEN` se configura a nivel de organización (ver sección [6.4](#64-secret-de-organización-kolonlabs_nuget_token)) y se propaga automáticamente a todos los repos mediante `secrets: inherit` en el workflow caller.

```yaml
jobs:
  build:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - name: Setup .NET
        uses: actions/setup-dotnet@v4
        with:
          dotnet-version: '{dotnet-version}'   # ej: 10.x

      - name: Restore
        run: dotnet restore
        env:
          KOLONLABS_NUGET_TOKEN: ${{ secrets.KOLONLABS_NUGET_TOKEN }}

      - name: Build
        run: dotnet build --no-restore -c Release
```

> **Para despliegues a Azure** (App Service, Container Apps, Functions): el build y el restore ocurren en el runner de GitHub Actions, no en Azure. Azure recibe los binarios ya compilados. El feed NuGet nunca necesita ser accesible desde Azure.

---

## 5. Referencia rápida de credenciales

| Escenario | Credencial | Scope requerido |
|---|---|---|
| Consumir en local | PAT en `KOLONLABS_NUGET_TOKEN` (variable de usuario) | `read:packages` |
| Consumir en GitHub Actions | Org secret `KOLONLABS_NUGET_TOKEN` (via `secrets: inherit`) | `read:packages` |
| Publicar desde GitHub Actions | Org secret `KOLONLABS_NUGET_TOKEN` (via `secrets: inherit`) | `write:packages` |
| Azure en runtime | — | No necesario |

> `GITHUB_TOKEN` **no funciona** para consumir paquetes de otros repositorios de la organización. Solo da acceso a los paquetes del repo donde se ejecuta el workflow.

---

## 6. Configurar un nuevo repositorio SDK

La lógica de CI y publicación está centralizada en el workflow reutilizable del repositorio `kolonlabs/.github`. Cada repositorio SDK solo necesita un fichero caller de ~15 líneas que invoca ese workflow centralizado.

### 6.1 Repositorio con un solo paquete

Crea `.github/workflows/publish.yml`:

```yaml
name: CI & Publish

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  workflow_dispatch:
    inputs:
      release_type:
        description: 'Tipo de release (rc | stable | vacío = solo CI)'
        required: false
        type: choice
        default: ''
        options: ['', rc, stable]

# Permisos top-level: necesarios para crear tags, releases y publicar paquetes.
# No poner permissions a nivel de job — causa startup_failure en workflows reutilizables.
permissions:
  contents: write
  packages: write

jobs:
  ci-publish:
    uses: KolonLabs/.github/.github/workflows/nuget-ci-publish.yml@main
    with:
      release_type: ${{ inputs.release_type || '' }}
    secrets: inherit
```

### 6.2 Repositorio con múltiples paquetes

El caller añade el input `package`. Es obligatorio en repos multi-paquete para evitar ambigüedad:

```yaml
name: CI & Publish

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  workflow_dispatch:
    inputs:
      release_type:
        description: 'Tipo de release (rc | stable | vacío = solo CI)'
        required: false
        type: choice
        default: ''
        options: ['', rc, stable]
      package:
        description: 'Paquete a publicar'
        required: false
        type: choice
        options:
          - ''
          - KL.{Paquete1}
          - KL.{Paquete2}

permissions:
  contents: write
  packages: write

jobs:
  ci-publish:
    uses: KolonLabs/.github/.github/workflows/nuget-ci-publish.yml@main
    with:
      release_type: ${{ inputs.release_type || '' }}
      package: ${{ inputs.package || '' }}
    secrets: inherit
```

Los comandos de publicación son los mismos descritos en las secciones 3.2, 3.3 y 3.5 — el caller expone los mismos inputs hacia el usuario final.

### 6.3 nuget.config

Copia el siguiente `nuget.config` a la raíz del nuevo repositorio:

```xml
<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <packageSources>
    <clear />
    <add key="NuGet official package source" value="https://api.nuget.org/v3/index.json" />
    <add key="KolonLabs" value="https://nuget.pkg.github.com/kolonlabs/index.json" />
  </packageSources>
  <packageSourceCredentials>
    <KolonLabs>
      <add key="Username" value="x" />
      <add key="ClearTextPassword" value="%KOLONLABS_NUGET_TOKEN%" />
    </KolonLabs>
  </packageSourceCredentials>
</configuration>
```

---

### 6.4 Secret de organización `KOLONLABS_NUGET_TOKEN`

Este secret es la pieza central que permite a todos los workflows de CI/CD de la organización consumir y publicar paquetes NuGet cross-repo. Se configura **una sola vez** a nivel de organización.

**Por qué es necesario:**
`GITHUB_TOKEN` en GitHub Actions solo tiene acceso a los paquetes del repositorio donde se ejecuta. Para acceder a paquetes de otros repos del mismo org (p.ej. `KL.Common` desde `sdk-common`), se devuelve un **403 Forbidden**. El org secret soluciona esto con un PAT que tiene permisos explícitos sobre todos los paquetes de la organización.

**Configuración inicial (una sola vez):**

1. Genera un Classic PAT con scopes:
   - `write:packages` (incluye `read:packages`)
   - `repo` (para acceso a repos privados)

2. Configura el secret a nivel de organización (visible para todos los repos):

```powershell
"ghp_TU_TOKEN" | gh secret set KOLONLABS_NUGET_TOKEN --org KolonLabs --visibility all
```

3. Los workflows usan `secrets: inherit` en el job caller, lo que propaga automáticamente este secret al workflow reutilizable.

**Renovación:** cuando el PAT expire, genera uno nuevo y repite el paso 2. No es necesario tocar ningún repositorio individual.
