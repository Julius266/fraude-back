# Plan: Chat RAG con Embeddings para fraude-back

> **Propósito:** Este documento describe exactamente qué se va a construir, por qué y cómo.  
> Se creó para leerse antes de ejecutar la implementación con Codex.

---

## 1. Contexto y por qué lo necesitamos

### Lo que ya existe
El proyecto `fraude-back` tiene:
- Ingestión de correos Gmail → extrae PDFs → parsea siniestros → los guarda en PostgreSQL (Neon).
- Scoring por reglas (`FraudScoringService`) y scoring con IA (`AIScoringService` con OpenAI tool-calling).
- `search_similar_claims` en `AIScoringService` usa **`SequenceMatcher`** — comparación carácter a carácter, lenta y sin semántica real.

### Lo que pide el reto (sección 10.2 + sección 12)
El reto exige un **agente de IA** que responda preguntas en lenguaje natural como:

| # | Pregunta que debe responder |
|---|-----------------------------|
| 1 | ¿Cuáles son los 10 siniestros con mayor riesgo de posible fraude? |
| 2 | ¿Por qué este siniestro fue marcado como alto riesgo? |
| 3 | ¿Qué proveedores concentran más alertas? |
| 4 | ¿Qué ramos tienen mayor porcentaje de casos sospechosos? |
| 5 | ¿Qué ciudades presentan mayor concentración de alertas? |
| 6 | ¿Qué asegurados tienen mayor frecuencia de reclamos? |
| 7 | ¿Qué documentos faltan en los casos críticos? |
| 8 | ¿Qué casos tienen montos atípicos? |
| 9 | ¿Qué siniestros ocurrieron cerca del inicio de la póliza? |
| 10 | ¿Qué patrones se repiten en los reclamos sospechosos? |
| 11 | Genera un resumen ejecutivo de los casos críticos. |
| 12 | Recomienda qué casos debería revisar primero el analista. |

### Solución: Chat RAG (Retrieval-Augmented Generation)
Un **chat** donde el usuario escribe en lenguaje natural y el sistema:
1. Convierte la pregunta en un **embedding** (vector numérico).
2. Busca los siniestros/correos más similares semánticamente en la base de datos (**vector search**).
3. Construye un contexto con esos documentos.
4. Llama a **GPT** con ese contexto para generar una respuesta fundamentada y explicable.

---

## 2. Arquitectura del módulo

```
Usuario (Bruno / frontend)
        │
        ▼
POST /api/v1/chat/query
        │
        ├─ 1. EmbeddingService.embed(pregunta)  ──► OpenAI text-embedding-3-small
        │
        ├─ 2. VectorSearchService.search(vector, k=8)
        │       └─ pgvector: SELECT ... ORDER BY embedding <=> $1 LIMIT k
        │
        ├─ 3. ContextBuilder.build(siniestros, correos, pregunta)
        │       └─ formatea los k documentos recuperados como contexto
        │
        └─ 4. ChatService.answer(contexto, pregunta)  ──► GPT-4.1 (chat completions)
                └─ Responde con base SOLO en el contexto + historial de chat
```

---

## 3. Componentes a crear

### 3.1 Extensión pgvector en Neon
Neon soporta `pgvector` nativamente. Solo hay que habilitarla y crear la columna.

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### 3.2 Nueva columna `embedding` en `siniestros`

```
siniestros.embedding  vector(1536)   -- text-embedding-3-small produce 1536 dims
```

Con índice HNSW para búsqueda eficiente:

```sql
CREATE INDEX ix_siniestros_embedding ON siniestros USING hnsw (embedding vector_cosine_ops);
```

### 3.3 Migración Alembic
Archivo: `alembic/versions/YYYYMMDD_0005_add_embeddings.py`

```python
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column("siniestros", sa.Column("embedding", Vector(1536), nullable=True))
    op.execute(
        "CREATE INDEX ix_siniestros_embedding ON siniestros "
        "USING hnsw (embedding vector_cosine_ops)"
    )

def downgrade():
    op.drop_index("ix_siniestros_embedding")
    op.drop_column("siniestros", "embedding")
```

### 3.4 Modelo ORM actualizado
`app/models/siniestro.py` — agregar columna:

```python
from pgvector.sqlalchemy import Vector
embedding = Column(Vector(1536), nullable=True)
```

### 3.5 `EmbeddingService`
`app/integrations/chat/embedding_service.py`

Responsabilidades:
- `embed_text(text: str) -> list[float]` — llama `text-embedding-3-small`.
- `embed_siniestro(siniestro: Siniestro) -> list[float]` — combina campos clave.
- Texto que se embedd por siniestro:

```
[{id_siniestro}] {ramo} - {cobertura} | {descripcion}
Asegurado: {id_asegurado} | Beneficiario: {beneficiario}
Estado: {estado} | Score color: calculado al vuelo
Monto reclamado: {monto_reclamado} | Días inicio póliza: {dias_desde_inicio_poliza}
```

### 3.6 `EmbeddingIndexService`
`app/integrations/chat/index_service.py`

Responsabilidades:
- `index_all(db)` — recorre todos los siniestros sin embedding, genera y guarda.
- `index_one(db, siniestro)` — genera y guarda el embedding de un siniestro.
- Se llama automáticamente al guardar un nuevo siniestro (hook post-commit) y desde el endpoint manual.

### 3.7 `VectorSearchService`
`app/integrations/chat/vector_search.py`

```python
def search(db: Session, query_vector: list[float], k: int = 8) -> list[Siniestro]:
    return db.scalars(
        select(Siniestro)
        .where(Siniestro.embedding.isnot(None))
        .order_by(Siniestro.embedding.cosine_distance(query_vector))
        .limit(k)
    ).all()
```

### 3.8 `ContextBuilder`
`app/integrations/chat/context_builder.py`

Convierte los `k` siniestros recuperados en un bloque de texto estructurado para el prompt:

```
=== SINIESTRO SIN-001 ===
Ramo: Vehículos | Cobertura: Robo total
Asegurado: AS-042 | Beneficiario: Taller XYZ
Estado: Reserva | Score: Rojo (24 pts)
Descripción: El vehículo fue reportado robado...
Alertas activadas: RS-01 (borde vigencia, 8pts), RF-01 (PTxRB)
Correo origen: asunto="SINIESTRO urgente", remitente=...
---
```

### 3.9 `ChatService`
`app/integrations/chat/chat_service.py`

- Mantiene **historial de conversación** por `session_id` (en memoria con TTL 30 min; Fase 1 sin persistencia).
- Construye el prompt con:
  - **System:** Rol de analista antifraude, instrucciones de responder solo con base en el contexto, no hacer acusaciones.
  - **Contexto RAG:** Los documentos recuperados.
  - **Historial:** Últimos N turnos.
  - **User:** La pregunta.
- Llama a `gpt-4.1` con `temperature=0.2`.

### 3.10 Endpoints del chat
`app/api/v1/endpoints/chat.py`

| Método | Ruta | Descripción |
|--------|------|-------------|
| `POST` | `/chat/query` | Enviar pregunta, recibir respuesta RAG |
| `POST` | `/chat/index` | Re-indexar todos los siniestros (regenera embeddings) |
| `GET` | `/chat/index/status` | Cuántos siniestros tienen embedding vs total |
| `DELETE` | `/chat/session/{session_id}` | Limpiar historial de sesión |

#### Body `POST /chat/query`
```json
{
  "question": "¿Cuáles son los siniestros con mayor riesgo?",
  "session_id": "analista-01",
  "k": 8
}
```

#### Response
```json
{
  "answer": "Basado en los datos analizados, los siniestros con mayor...",
  "sources": [
    { "id_siniestro": "SIN-001", "score_color": "Rojo", "similarity": 0.92 }
  ],
  "session_id": "analista-01",
  "model": "gpt-4.1"
}
```

---

## 4. Dependencias nuevas a instalar

```
pgvector>=0.3.0         # Driver Python para pgvector (columnas Vector)
```

Solo una línea a agregar en `requirements.txt`. OpenAI ya está instalado y tiene el endpoint de embeddings.

---

## 5. Variables de entorno nuevas

| Variable | Descripción | Default |
|----------|-------------|---------|
| `EMBEDDING_MODEL` | Modelo OpenAI para embeddings | `text-embedding-3-small` |
| `CHAT_MODEL` | Modelo para el chat | usa `OPENAI_MODEL` |
| `CHAT_K_RESULTS` | Número de documentos a recuperar por búsqueda | `8` |
| `CHAT_MAX_HISTORY` | Turnos de historial a mantener por sesión | `10` |
| `CHAT_SESSION_TTL_SECONDS` | TTL de sesión en memoria | `1800` |

Agregar a `config.py` y a `.env.example`.

---

## 6. Flujo completo paso a paso

```
Nuevo correo llega por Gmail push
        │
        ▼
GmailIngestionService._process_message()
        │ guarda GmailCorreo + Siniestro
        ▼
EmbeddingIndexService.index_one(siniestro)   ← NUEVO
        │ genera embedding con OpenAI
        ▼
UPDATE siniestros SET embedding = [...] WHERE id_siniestro = ...
        │
        ▼
Analista abre chat
        │
POST /api/v1/chat/query { "question": "...", "session_id": "..." }
        │
        ├─ embed(question)  →  vector[1536]
        ├─ pgvector cosine search → top-k siniestros
        ├─ build_context(siniestros)
        └─ GPT-4.1 → respuesta fundamentada
```

---

## 7. System prompt del agente de chat

```
Eres un asistente de análisis antifraude para la Aseguradora del Sur.
Tienes acceso a siniestros analizados previamente por el sistema de detección de fraude.

REGLAS IMPORTANTES:
- Responde SIEMPRE en español.
- Basa tus respuestas ÚNICAMENTE en el contexto de siniestros proporcionado.
- Nunca acuses a un asegurado de fraude; usa el lenguaje "posible riesgo" o "requiere revisión".
- Si no tienes suficiente información en el contexto, dilo claramente.
- Cuando respondas con listas de siniestros, ordénalos por nivel de riesgo (Rojo > Amarillo > Verde).
- Cita siempre los IDs de siniestro en tu respuesta.
- Tu función es ayudar al analista humano a priorizar casos, no tomar decisiones.

CONTEXTO DE SINIESTROS RECUPERADOS:
{context}
```

---

## 8. Preguntas predefinidas (quick actions)

Para la demo del hackathon, el endpoint aceptará también `preset_question`:

| ID | Pregunta |
|----|---------|
| `top10_risk` | ¿Cuáles son los 10 siniestros con mayor riesgo de posible fraude? |
| `why_flagged` | ¿Por qué el siniestro `{id}` fue marcado como alto riesgo? |
| `provider_alerts` | ¿Qué proveedores concentran más alertas? |
| `branch_risk` | ¿Qué ramos tienen mayor porcentaje de casos sospechosos? |
| `high_frequency` | ¿Qué asegurados tienen mayor frecuencia de reclamos? |
| `missing_docs` | ¿Qué documentos faltan en los casos críticos? |
| `exec_summary` | Genera un resumen ejecutivo de los casos críticos. |
| `analyst_queue` | Recomienda qué casos debería revisar primero el analista. |

---

## 9. Archivos a crear / modificar

### Nuevos
```
app/
  api/v1/endpoints/chat.py
  integrations/chat/
    __init__.py
    embedding_service.py
    index_service.py
    vector_search.py
    context_builder.py
    chat_service.py
  schemas/chat.py
alembic/versions/YYYYMMDD_0005_add_embeddings.py
```

### Modificados
```
app/models/siniestro.py            ← columna embedding
app/core/config.py                 ← EMBEDDING_MODEL, CHAT_K_RESULTS, etc.
app/api/v1/router.py               ← incluir chat_router
app/integrations/gmail/service.py  ← llamar index_one tras guardar siniestro
requirements.txt                   ← pgvector
.env.example                       ← nuevas variables
README.md                          ← sección Chat RAG
```

---

## 10. Orden de implementación (para Codex)

1. `pip install pgvector` → actualizar `requirements.txt`.
2. Nuevas variables en `app/core/config.py`.
3. Migración Alembic `0005_add_embeddings` + `alembic upgrade head`.
4. Actualizar `app/models/siniestro.py` con columna `Vector(1536)`.
5. Crear `app/integrations/chat/embedding_service.py`.
6. Crear `app/integrations/chat/index_service.py`.
7. Crear `app/integrations/chat/vector_search.py`.
8. Crear `app/integrations/chat/context_builder.py`.
9. Crear `app/integrations/chat/chat_service.py`.
10. Crear `app/schemas/chat.py` (Pydantic request/response).
11. Crear `app/api/v1/endpoints/chat.py`.
12. Registrar router en `app/api/v1/router.py`.
13. Conectar `index_one` en `GmailIngestionService` tras guardar siniestro.
14. Probar con `GET /chat/index/status` → `POST /chat/index` → `POST /chat/query`.

---

## 11. Consideraciones técnicas

### pgvector en Neon
Neon soporta pgvector. Solo se necesita `CREATE EXTENSION IF NOT EXISTS vector` en la migración. No requiere configuración adicional en la base de datos.

### Modelo de embedding
`text-embedding-3-small` (1536 dimensiones):
- Costo: $0.02 / 1M tokens.
- Velocidad: ~100ms por siniestro.
- Para 1000 siniestros ≈ $0.02 total.

### Historial de sesión en memoria
Fase 1: diccionario en Python `{session_id: deque(messages, maxlen=20)}`. Se limpia con TTL. No persiste entre reinicios del servidor. Es suficiente para la demo del hackathon.

Fase 2 (post-hackathon): tabla `chat_sessions` en PostgreSQL.

### Fallback sin embeddings
Si un siniestro no tiene embedding todavía, el `VectorSearchService` lo omite automáticamente (`WHERE embedding IS NOT NULL`). La respuesta puede tener menos contexto pero no falla.

### SequenceMatcher → pgvector
El método `_search_similar_claims` en `AIScoringService` actualmente usa `SequenceMatcher`. En Fase 2 (post-demo) se puede reemplazar por la búsqueda vectorial para mayor precisión semántica.

---

## 12. Criterios de éxito

- [ ] `POST /chat/index` genera embeddings para todos los siniestros existentes sin errores.
- [ ] `GET /chat/index/status` muestra `indexed/total`.
- [ ] `POST /chat/query` con "¿Cuáles son los siniestros más sospechosos?" devuelve respuesta coherente con IDs reales.
- [ ] El chat mantiene contexto entre turnos de la misma `session_id`.
- [ ] La respuesta cita siniestros reales y usa lenguaje de "posible riesgo", no de acusación.
- [ ] Responde correctamente las 12 preguntas del reto (sección 12 del PDF).

---

## 13. Ejemplo de llamada de demo

```http
POST http://127.0.0.1:8000/api/v1/chat/query
Content-Type: application/json

{
  "question": "Recomiéndame los 5 casos que debería revisar primero el analista y explica por qué",
  "session_id": "demo-hackathon",
  "k": 10
}
```

Respuesta esperada:
```json
{
  "answer": "Basado en el análisis de los siniestros cargados, recomiendo revisar con prioridad:\n\n1. **SIN-007** (Rojo, 24 pts)...",
  "sources": [
    { "id_siniestro": "SIN-007", "score_color": "Rojo", "similarity": 0.94 },
    ...
  ],
  "session_id": "demo-hackathon",
  "model": "gpt-4.1"
}
```
