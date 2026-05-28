# Plan de implementación — Detector de Posibles Fraudes

## Qué vamos a construir

Un backend FastAPI que recibe siniestros, los analiza con reglas de negocio + embeddings + ML y devuelve un **score de riesgo 0–100** con semáforo verde / amarillo / rojo, alertas explicables y un agente de consulta en lenguaje natural.

---

## Arquitectura general

```
[Dataset sintético]
        │
        ▼
[POST /api/v1/siniestros]  ←── carga individual o bulk
        │
        ├── 1. Reglas de negocio  →  puntos por señal
        ├── 2. Score numérico      →  suma ponderada
        ├── 3. Embeddings NLP      →  similitud de narrativas
        ├── 4. (futuro) ML model   →  clasificador supervisado
        │
        ▼
[GET /api/v1/siniestros/{id}/score]   →  score + alertas + semáforo
[GET /api/v1/siniestros/ranking]      →  top casos de riesgo
[POST /api/v1/agent/query]            →  preguntas en lenguaje natural
```

---

## Módulos a implementar

### 1. Reglas de negocio (`app/rules/fraud_rules.py`)

Implementar las señales del PDF con sus puntajes exactos:

| Código | Señal | Pts máx |
|--------|-------|---------|
| R01 | Reclamo ≤ 10 días inicio póliza | 8 |
| R02 | Reclamo ≤ 30 días inicio póliza | 4 |
| R03 | Reporte tardío robo > 48h | 8 |
| R04 | Asegurado ≥ 3 siniestros (18 meses) | 8 |
| R05 | Asegurado 2 siniestros (18 meses) | 4 |
| R06 | Vehículo ≥ 3 siniestros (18 meses) | 6 |
| R07 | Beneficiario en lista restrictiva | 10 |
| R08 | Beneficiario en 2+ casos observados | 5 |
| R09 | Documentos incompletos | 4 |
| R10 | Reporte tardío > 7 días | 5 |
| R11 | Reporte tardío 4–7 días | 3 |
| R12 | Monto ≥ 95% suma asegurada | 4 |
| R13 | Narrativa similar > 85% a otro siniestro | 8 |
| R14 | Narrativa similar 70–84% | 4 |
| **Total máx** | | **~85** → normalizado a 100 |

Semáforo:
- 0–40 → verde
- 41–75 → amarillo
- 76–100 → rojo

---

### 2. Embeddings + similitud de narrativas (`app/services/embeddings.py`)

**Por qué embeddings:**
El reto pide detectar "narrativas similares" entre siniestros (R13/R14). La forma correcta es vectorizar `descripcion` y calcular similitud coseno.

**Stack:**
- `pgvector` (extensión Postgres/Neon) — guardar y consultar vectores
- `pgvector` para SQLAlchemy (`pgvector[psycopg2]`)
- Modelo de embeddings: **Gemini text-embedding-004** (Google, 768 dims, gratuito con API key) o **sentence-transformers** (local, sin API key)

**Flujo:**
```
siniestro.descripcion
        │
        ▼
EmbeddingService.generate(text) → vector float[768]
        │
        ▼
guardar en siniestros.descripcion_vector (columna VECTOR(768))
        │
        ▼
SimilarityService.find_similar(id) → otros siniestros con cosine > 0.70
        │
        ▼
FraudRules: +8 pts si > 0.85, +4 pts si 0.70–0.84
```

**Migración Alembic a crear:**
```sql
CREATE EXTENSION IF NOT EXISTS vector;
ALTER TABLE siniestros ADD COLUMN descripcion_vector vector(768);
CREATE INDEX ON siniestros USING hnsw (descripcion_vector vector_cosine_ops);
```

---

### 3. Score final (`app/services/fraud_score.py`)

```python
def calcular_score(siniestro) -> FraudScore:
    puntos = aplicar_reglas(siniestro)          # reglas R01–R12
    puntos += similitud_narrativa(siniestro)     # R13–R14 (embeddings)
    score = min(int((puntos / 85) * 100), 100)
    nivel = "rojo" if score >= 76 else "amarillo" if score >= 41 else "verde"
    alertas = [regla.descripcion for regla in reglas_activas]
    return FraudScore(score=score, nivel=nivel, alertas=alertas)
```

---

### 4. Agente IA (`app/services/agent.py`)

Agente de consulta en lenguaje natural usando **Gemini** (ya tenemos Google API key en credentials). Responde las preguntas del reto:

- "¿Cuáles son los 10 siniestros con mayor riesgo?"
- "¿Por qué este siniestro fue marcado como alto riesgo?"
- "¿Qué proveedores concentran más alertas?"
- etc.

Implementación: función-calling con las queries SQL ya hechas como "tools" del agente.

---

### 5. Endpoints nuevos a crear

| Método | Ruta | Descripción |
|--------|------|-------------|
| `POST` | `/api/v1/siniestros/bulk` | Carga masiva de dataset |
| `POST` | `/api/v1/siniestros/{id}/score` | Calcular y guardar score |
| `POST` | `/api/v1/siniestros/score-all` | Score para todos los pendientes |
| `GET` | `/api/v1/siniestros/ranking` | Top siniestros por score desc |
| `GET` | `/api/v1/siniestros/{id}/score` | Score + alertas de un siniestro |
| `POST` | `/api/v1/agent/query` | Consulta en lenguaje natural |

---

## Orden de implementación

1. **Migración pgvector** — habilitar extensión + columna `descripcion_vector` en Neon
2. **`requirements.txt`** — agregar `pgvector` y cliente de embeddings
3. **`app/services/embeddings.py`** — servicio de generación y consulta de vectores
4. **`app/rules/fraud_rules.py`** — todas las reglas del PDF con sus pesos
5. **`app/services/fraud_score.py`** — calcula score combinando reglas + similitud
6. **Columna `score` en `siniestros`** — guardar resultado (migración)
7. **Endpoints de score y ranking**
8. **Dataset sintético** — script para generar 500+ registros en `data/synthetic/`
9. **`app/services/agent.py`** — agente con Gemini para lenguaje natural
10. **Endpoint `/agent/query`**

---

## Decisiones técnicas clave

| Decisión | Elección | Por qué |
|----------|----------|---------|
| ORM | SQLAlchemy (ya existe) | Consistencia |
| Vector DB | pgvector en Neon | Todo en un mismo Postgres, sin infra extra |
| Embeddings | Gemini text-embedding-004 | Gratis, 768 dims, ya tenemos Google creds |
| Agente IA | Gemini + function calling | Misma API, sin dependencias extra |
| Similitud | Coseno (HNSW index) | Rápido, estándar para NLP |
| Score | Reglas ponderadas + similitud | Explicable (exigido por el reto, 25% criterio) |

---

## Lo que NO hacemos (por el reto)

- No acusar automáticamente a nadie
- No rechazar siniestros
- No usar datos personales reales
- Siempre indicar que es una "alerta para revisión humana"
