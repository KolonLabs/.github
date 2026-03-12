# KolonLabs Framework · Contexto Cross-Repo mediante MCP Server

> Diseño de Arquitectura · v1.1

---

## 1. Contexto y Problema

La organización dispone de múltiples repositorios GitHub que encapsulan el acceso a infraestructura Azure: CosmosDB, Event Grid, Data Explorer, Storage, middlewares, etc. Estos repos exponen paquetes NuGet internos que deben utilizarse en lugar de los SDKs directos de Microsoft.

**El problema:** GitHub Copilot, al trabajar en un repo consumidor, no tiene conocimiento de las interfaces, patrones y convenciones de los repos de infraestructura, por lo que tiende a generar código usando los SDKs de Microsoft directamente en lugar de las abstracciones internas.

**Objetivo:** Que GitHub Copilot (y Claude Code) genere automáticamente código que use las librerías internas KolonLabs, sin necesidad de clonar los repos de infraestructura localmente.

---

## 2. Solución Propuesta

Un **MCP Server local genérico** que se comunica con la GitHub API para leer el código de los repos de infraestructura en tiempo real, exponiendo sus interfaces y patrones de uso al agente de IA.

### Flujo de comunicación

```
GitHub Copilot / Claude Code
        │
        │  tools/list  (al arrancar)
        ▼
KolonLabs-mcp-server  (proceso local, stdio)
        │
        │  GitHub API  (PAT de la org)
        ▼
Repos privados de la org
 ├── KL.Data.Cosmos
 ├── KL.Messaging.EventGrid
 ├── KL.Storage.Blob
 └── [nuevo repo]  ← descubierto automáticamente
```

### Handshake MCP

Al arrancar el agente, el protocolo MCP realiza una fase de descubrimiento estándar:

1. Copilot llama a `tools/list` en el MCP server
2. El server llama a la GitHub API y lista todos los repos con el topic `kl-framework`
3. Lee el `mcp-manifest.json` de cada repo descubierto
4. Devuelve a Copilot la lista consolidada de herramientas con sus descripciones
5. A partir de ese momento el modelo conoce todas las herramientas disponibles

---

## 3. Descubrimiento Dinámico de Repos

El MCP server **no tiene conocimiento hardcodeado** de ningún repositorio. Utiliza una convención basada en GitHub Topics para descubrirlos automáticamente.

### Convención de registro

Para que un repo sea descubierto, únicamente necesita:

- Tener el GitHub Topic **`kl-framework`** asignado en el repositorio
- Contener un archivo **`mcp-manifest.json`** en la raíz

No se requiere ningún cambio en el MCP server. El nuevo repo queda disponible en el siguiente arranque del agente.

### Estructura del `mcp-manifest.json`

```json
{
  "name": "KL.Data.Cosmos",
  "description": "Acceso a CosmosDB. Usar SIEMPRE en lugar de Microsoft.Azure.Cosmos",
  "replaces": ["Microsoft.Azure.Cosmos"],
  "packages": ["KL.Data.Cosmos"],
  "entryPoints": ["src/KL.Data.Cosmos", "examples"],
  "tools": [
    {
      "name": "get_cosmos_interfaces",
      "description": "Obtener interfaces públicas de CosmosDB. Llamar SIEMPRE que
        se vaya a generar código de acceso a CosmosDB, entidades, contenedores
        o queries a base de datos",
      "files": [
        "src/KL.Data.Cosmos/Abstractions/ICosmosRepository.cs",
        "src/KL.Data.Cosmos/Abstractions/ICosmosContext.cs",
        "examples/01_Registration.cs"
      ]
    },
    {
      "name": "get_cosmos_examples",
      "description": "Obtener ejemplos de uso e inyección de dependencias",
      "files": [
        "examples/02_QueryPatterns.cs",
        "examples/03_EntityExample.cs"
      ]
    }
  ]
}
```

### Schema completo de campos

| Campo | Tipo | Obligatorio | Descripción |
|---|---|---|---|
| `name` | string | ✓ | Identificador del repo en el MCP server |
| `description` | string | ✓ | Descripción del paquete — visible en `tools/list` |
| `replaces` | string[] | ✓ | SDKs de Microsoft/Azure que este paquete sustituye |
| `packages` | string[] | ✓ | Nombres NuGet de los paquetes del repo |
| `entryPoints` | string[] | ✓ | Carpetas raíz para descubrimiento genérico (fallback) |
| `tools[].name` | string | ✓ | Nombre de la herramienta MCP |
| `tools[].description` | string | ✓ | Trigger de invocación automática — ver sección 5 |
| `tools[].files` | string[] | recomendado | Archivos exactos a servir. Si ausente, el server usa `entryPoints` completos |

> **`files` vs `entryPoints`:** Usar `files` por herramienta siempre que sea posible para evitar saturar el contexto del modelo. `entryPoints` queda como fallback para repos que no lo definan o para herramientas genéricas de exploración.

---

## 3b. Cómo Registrar un Repo Nuevo

Pasos para que un repo de infraestructura sea descubierto y sirva su código al agente:

```
1. Ir a Settings del repo en GitHub → Topics → añadir: kl-framework

2. Crear README.md en la raíz del repo  ← para el desarrollador humano
   (ver sección 3c)

3. Crear carpeta examples/ con 2-4 snippets de uso  ← para el agente IA
   · 01_Registration.cs   → cómo registrar en Program.cs / DI
   · 02_BasicUsage.cs     → uso más frecuente
   · 03_AdvancedUsage.cs  → casos avanzados (opcional)

4. Crear mcp-manifest.json en la raíz del repo  ← para el MCP server
   (ver schema en sección 3 y herramientas estándar en sección 3c)

5. En KL.*.csproj añadir:
   <PackageReadmeFile>README.md</PackageReadmeFile>
   <None Include="..\..\README.md" Pack="true" PackagePath="\" />

6. El repo queda disponible en el próximo arranque del MCP server.
   Sin cambios en el server.
```

---

## 3c. Herramientas Estándar por Repo

Cada repo define sus propias herramientas según lo que expone, pero hay un conjunto de herramientas estándar que **todo repo debe incluir**:

### Herramientas obligatorias

| Tool | Sirve | Trigger típico |
|---|---|---|
| `get_<dominio>_setup` | Archivos de registro DI + `examples/01_Registration.cs` | "configura", "registra", "añade al DI", "Program.cs" |
| `get_<dominio>_api` | Interfaces/clases públicas + ejemplos de uso básico | "crea", "implementa", "usa", nombre del paquete |
| `get_readme` | `README.md` | "cómo funciona", "qué hace", "documentación", "error de config" |

### Herramientas opcionales (según el dominio)

| Tool | Sirve | Cuándo añadirla |
|---|---|---|
| `get_<dominio>_examples` | Todos los archivos de `examples/` | Si los ejemplos son numerosos o especializados |
| `get_<dominio>_patterns` | Patrones avanzados, queries, pipelines | Repos con DSL propio (CosmosDB queries, KQL, etc.) |
| `get_<dominio>_models` | Entidades, DTOs, enums públicos | Repos con modelos de datos |

### Ejemplo de manifest mínimo completo

```json
{
  "name": "KL.MiLibreria",
  "description": "Descripción del dominio. Usar SIEMPRE en lugar de [SDK que reemplaza].",
  "replaces": ["Nombre.Del.SDK.Reemplazado"],
  "packages": ["KL.MiLibreria"],
  "entryPoints": ["src/KL.MiLibreria", "examples"],
  "tools": [
    {
      "name": "get_milibreria_setup",
      "description": "Obtener cómo registrar KL.MiLibreria en ASP.NET Core. Llamar SIEMPRE que se configure o registre [dominio] en el DI. Nunca usar [SDK directo].",
      "files": [
        "src/KL.MiLibreria/ServiceCollectionExtensions.cs",
        "examples/01_Registration.cs"
      ]
    },
    {
      "name": "get_milibreria_api",
      "description": "Obtener interfaces y patrones de uso de KL.MiLibreria. Llamar SIEMPRE que se genere código que interactúe con [dominio].",
      "files": [
        "src/KL.MiLibreria/Abstractions/IMiServicio.cs",
        "examples/02_BasicUsage.cs"
      ]
    },
    {
      "name": "get_readme",
      "description": "Obtener documentación completa de KL.MiLibreria. Llamar cuando el desarrollador pregunte cómo usar el paquete, qué hace, cómo instalarlo, o ante errores de configuración.",
      "files": [
        "README.md"
      ]
    }
  ]
}
```

---

## 3d. README — Para el Desarrollador, No Para el Agente

El `README.md` y los archivos de `examples/` tienen audiencias distintas y no deben mezclarse:

| | `README.md` | `examples/*.cs` |
|---|---|---|
| **Audiencia** | Desarrollador humano | Agente IA (Copilot, Claude) |
| **Acceso** | GitHub, NuGet Browser, `get_readme` tool | Herramientas MCP del manifest |
| **Contenido** | Explicación del propósito, instalación, configuración paso a paso, referencia de API, errores comunes | Snippets de código compilables, sin prosa explicativa, con comentarios `// ✓` y `// ✗` |
| **Tono** | Tutorial narrativo | Código directo como contexto |

### Secciones obligatorias del README

```
1. ¿Cuándo usarlo?       — delimita exactamente el rol del paquete
2. Instalación           — PackageReference + referencia al feed NuGet privado
3. Configuración         — paso a paso: secrets, appsettings, Program.cs
4. Uso                   — snippets clave con lo que SÍ y NO hacer
5. Referencia de API     — tabla de métodos/extensiones públicas
6. Errores comunes       — los 3-5 problemas más frecuentes con causa y solución
```

---

## 4. Herramientas por Repo

Cada repo define su propio conjunto de herramientas. El MCP server las registra y expone dinámicamente.

| Repositorio | Herramientas expuestas | SDK que reemplaza |
|---|---|---|
| `KL.Data.Cosmos` | `get_interfaces`, `get_examples`, `get_query_patterns` | `Microsoft.Azure.Cosmos` |
| `KL.Messaging.EventGrid` | `get_event_schema`, `get_publisher_examples` | `Azure.Messaging.EventGrid` |
| `KL.Storage.Blob` | `get_container_policy`, `get_upload_examples` | `Azure.Storage.Blobs` |
| `KL.DataExplorer` | `get_kql_patterns`, `get_client_setup` | `Microsoft.Azure.Kusto` |
| `KL.Middleware.*` | `get_pipeline_config`, `get_middleware_chain` | (varios) |
| `[nuevo repo]` | definidas en su `mcp-manifest.json` | según corresponda |

---

## 5. Invocación Automática por el Agente

En **modo Agent**, GitHub Copilot y Claude Code determinan automáticamente cuándo invocar una herramienta MCP basándose en la descripción de la herramienta y el contexto de la petición.

### Ejemplo de razonamiento del agente

```
Usuario: "crea un repositorio para guardar entidades Order en CosmosDB"

Agente razona internamente:
  → la petición involucra CosmosDB
  → tengo herramienta get_cosmos_interfaces (KL.Data.Cosmos)
  → su descripción dice: llamar SIEMPRE que se genere código de CosmosDB
  → invoca la herramienta → obtiene ICosmosRepository<T>, ICosmosContext...
  → genera código usando las interfaces internas, no el SDK directo
```

### Clave: descripciones como triggers

La calidad de la invocación automática depende directamente de cómo se redactan las descripciones en el `mcp-manifest.json`:

```
✗  POBRE:  "Devuelve interfaces de CosmosDB"

✓  BUENA:  "Obtener interfaces y patrones de KL.Data.Cosmos. Llamar SIEMPRE
            que se vaya a generar código de acceso a CosmosDB, entidades,
            contenedores o queries. Nunca usar Microsoft.Azure.Cosmos directamente."
```

Una buena descripción incluye:
- El contexto en el que se debe invocar la herramienta
- Palabras clave que el usuario podría usar en su petición
- Indicación explícita de cuándo es obligatorio llamarla

---

## 5b. Arquitectura Interna del MCP Server

El server es un proceso Node.js (o .NET) que implementa el protocolo MCP sobre stdio. Su lógica es completamente genérica — no contiene conocimiento de ningún repo.

```
┌─────────────────────────────────────────┐
│           kl-mcp-server                 │
│                                         │
│  ┌─────────────┐   ┌─────────────────┐  │
│  │ MCP Handler │   │  GitHub Client  │  │
│  │             │   │                 │  │
│  │ tools/list ─┼───┼→ search repos   │  │
│  │             │   │  by topic       │  │
│  │             │   │  read manifests │  │
│  │ tool/call  ─┼───┼→ read files[]   │  │
│  │             │   │  from manifest  │  │
│  └─────────────┘   └─────────────────┘  │
│                                         │
│  ┌─────────────────────────────────────┐│
│  │  Cache en memoria (TTL: 5 min)      ││
│  │  repos descubiertos + manifests     ││
│  └─────────────────────────────────────┘│
└─────────────────────────────────────────┘
```

### Flujo `tools/list` (arranque del agente)

```
1. GET /search/repositories?q=topic:kl-framework+org:{ORG}
2. Por cada repo encontrado:
   GET /repos/{org}/{repo}/contents/mcp-manifest.json
   → decodifica base64 → parsea JSON
3. Por cada tool en cada manifest:
   → registra { name, description } en la lista de herramientas
4. Devuelve lista consolidada a Copilot
   → Copilot ya conoce todas las tools disponibles
```

### Flujo `tool/call` (invocación de herramienta)

```
1. Copilot llama a tool: "get_google_auth_setup"
2. Server busca la tool en los manifests cacheados
3. Lee los archivos declarados en tools[].files:
   GET /repos/{org}/{repo}/contents/{file}  (por cada file)
   → decodifica base64 → texto plano
4. Concatena los contenidos con cabeceras de archivo
5. Devuelve el texto a Copilot como resultado de la herramienta
6. Copilot usa ese código fuente como contexto para generar
```

### Gestión de errores

- Repo con topic `kl-framework` pero sin `mcp-manifest.json` → se ignora, no falla el `tools/list`
- Archivo en `files[]` no encontrado en GitHub → se omite con warning, no falla la tool
- Rate limit de GitHub API → respuesta 429, el server retorna error descriptivo al agente
- PAT ausente o inválido → error en arranque con mensaje claro

---

## 6. Configuración en los Repos Consumidores

El MCP server se configura una única vez en la máquina del desarrollador. En cada repo consumidor se añade un archivo de configuración que apunta al servidor local.

### `.vscode/mcp.json`

```json
{
  "servers": {
    "kl-framework": {
      "type": "stdio",
      "command": "npx",
      "args": ["kl-mcp-server"],
      "env": {
        "GITHUB_TOKEN": "${env:GITHUB_TOKEN}",
        "GITHUB_ORG": "kolonlabs"
      }
    }
  }
}
```

### Variable de entorno

Solo es necesario un Personal Access Token (PAT) de GitHub con permisos de lectura sobre los repos de la org:

```powershell
# Windows (PowerShell) — añadir al perfil para que persista
$env:GITHUB_TOKEN = "ghp_xxxxxxxxxxxxxxxxxxxx"
```

> **Seguridad:** el PAT nunca debe commitearse. El `mcp.json` lo referencia como variable de entorno (`${env:GITHUB_TOKEN}`), no como valor literal.

---

## 7. Ventajas del Enfoque

| Aspecto | Comportamiento |
|---|---|
| Repos clonados localmente | No requerido. El MCP lee desde GitHub API en tiempo real |
| Nuevo repo de infraestructura | Solo añadir topic y `mcp-manifest.json`. Cero cambios en el servidor |
| Nuevas herramientas en un repo | Añadir entrada en `mcp-manifest.json` del repo correspondiente |
| Versión del código | Siempre la rama `main`. Sin desfase entre local y remoto |
| Compatibilidad | Copilot Agent, Claude Code, Cursor y cualquier cliente MCP |
| Infraestructura necesaria | Ninguna. Proceso local stdio, sin Azure ni servidores remotos |

---

## 8. Plan de Implementación

### Fase 1 · MCP Server base (Node.js)
- Proyecto Node.js/TypeScript con `@modelcontextprotocol/sdk`
- Llamada a GitHub API para listar repos por topic `kl-framework`
- Lectura de `mcp-manifest.json` de cada repo descubierto
- Registro dinámico de herramientas en `tools/list`
- Caché en memoria con TTL de 5 minutos para manifests y archivos
- Gestión de errores: repos sin manifest, archivos ausentes, rate limit

### Fase 2 · Herramientas genéricas
- Soporte completo para `tools[].files` → sirve solo los archivos declarados
- Fallback a `entryPoints` cuando `files` no está definido
- `get_readme` → lee `README.md` del repo vía GitHub API

### Fase 3 · Manifests en repos de infraestructura
- Añadir topic `kl-framework` a cada repo existente
- Crear `mcp-manifest.json` con `files` por herramienta
- Crear carpeta `examples/` con snippets de uso
- Validar invocación automática en Copilot Agent y Claude Code

### Fase 4 · Distribución como paquete npm
- Publicar `kl-mcp-server` en npm (público o privado según la org)
- Los desarrolladores lo usan via `npx kl-mcp-server` — sin instalación previa
- O instalación global: `npm install -g kl-mcp-server`
- Añadir `.vscode/mcp.json` a cada repo consumidor como estándar de la org
- Documentar onboarding: solo instalar Node.js + configurar `GITHUB_TOKEN`

> **Por qué npm sobre dotnet tool:** Node.js está disponible en cualquier máquina de desarrollador independientemente del stack del proyecto. Un desarrollador de un repo no-.NET también puede usar el MCP server sin instalar el SDK de .NET. `npx` permite ejecutarlo sin instalación previa.
