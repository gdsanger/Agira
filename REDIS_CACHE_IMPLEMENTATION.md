# Redis Cache für AI Agents - Implementierungsdokumentation

## Übersicht

Diese Implementierung fügt einen Redis-basierten Response-Cache für AI Agents hinzu, um Laufzeit und KI-Kosten zu reduzieren. Die Lösung ist vollständig über YAML konfigurierbar und resilient gegenüber Redis-Ausfällen.

## Features

- ✅ **YAML-konfigurierbar**: Cache-Einstellungen pro Agent konfigurierbar
- ✅ **TTL-Support**: Konfigurierbare Ablaufzeit für gecachte Antworten
- ✅ **Content-basierte Keys**: SHA256-Hash des Eingabetexts
- ✅ **Agent-Versioning**: Unterschiedliche Versionen desselben Agenten haben separate Caches
- ✅ **Resilient**: Redis-Fehler führen nicht zu Anfragen-Fehlschlägen
- ✅ **Backward Compatible**: Agenten ohne Cache-Konfiguration funktionieren unverändert

## Konfiguration

### 1. Redis-Verbindung (.env)

```bash
# Redis Cache für AI Agent Response Cache
REDIS_CACHE_ENABLED=True
REDIS_CACHE_HOST=localhost
REDIS_CACHE_PORT=6379
REDIS_CACHE_DB=0
REDIS_CACHE_PASSWORD=
REDIS_CACHE_SOCKET_TIMEOUT=5
REDIS_CACHE_SOCKET_CONNECT_TIMEOUT=5
```

### 2. Agent-Konfiguration (YAML)

```yaml
name: my-agent
description: Mein Agent mit Cache
provider: OpenAI
model: gpt-4o
role: Du bist ein Experte...
task: "Deine Aufgabe ist..."

# Cache-Konfiguration (optional)
cache:
  enabled: true              # Cache aktivieren/deaktivieren
  ttl_seconds: 7776000       # 90 Tage (Standard)
  key_strategy: content_hash # Nur content_hash unterstützt
  agent_version: 1           # Version für Cache-Key (Standard: 1)
```

### Konfigurationsregeln

| Feld | Default | Beschreibung |
|------|---------|--------------|
| `cache` | nicht vorhanden | Wenn fehlt: Cache deaktiviert |
| `enabled` | `false` | Cache muss explizit aktiviert werden |
| `ttl_seconds` | `7776000` (90 Tage) | Ablaufzeit in Sekunden |
| `key_strategy` | `content_hash` | Nur `content_hash` unterstützt |
| `agent_version` | `1` | Version für Cache-Namespace |

## Cache-Key-Format

```
aiagent:{agent_name}:v{agent_version}:{sha256(input_text)}
```

**Beispiel:**
```
aiagent:summarize-text-agent:v1:a3f5b8c9d2e1f0...
```

### Eigenschaften

- **Deterministisch**: Gleicher Input → Gleicher Key
- **Agent-spezifisch**: Gleicher Input bei verschiedenen Agenten → Unterschiedliche Keys
- **Versioniert**: Gleicher Input mit verschiedenen Versionen → Unterschiedliche Keys

## Request-Flow

```
┌─────────────────────────────────────────────────────────────┐
│ AgentService.execute_agent(filename, input_text)            │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. Load Agent YAML Configuration                            │
│    - Parse cache config with defaults                       │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. Check if Cache Enabled                                   │
│    - Global: REDIS_CACHE_ENABLED                            │
│    - Agent: cache.enabled                                   │
│    - Redis Connection OK                                    │
└─────────────────────────────────────────────────────────────┘
                          │
                ┌─────────┴─────────┐
                │                   │
            Cache OFF          Cache ON
                │                   │
                │                   ▼
                │    ┌──────────────────────────────────────┐
                │    │ 3. Build Cache Key                   │
                │    │    SHA256(input_text) + agent + ver  │
                │    └──────────────────────────────────────┘
                │                   │
                │                   ▼
                │    ┌──────────────────────────────────────┐
                │    │ 4. Redis GET (cache_key)             │
                │    └──────────────────────────────────────┘
                │                   │
                │         ┌─────────┴─────────┐
                │         │                   │
                │      CACHE HIT         CACHE MISS
                │         │                   │
                │         ▼                   │
                │    ┌────────────────┐       │
                │    │ Return Cached  │       │
                │    │ Response       │       │
                │    │ (no AI call)   │       │
                │    └────────────────┘       │
                │                             │
                └─────────────┬───────────────┘
                              │
                              ▼
               ┌──────────────────────────────────────┐
               │ 5. Execute AI Request                │
               │    AIRouter.generate()               │
               └──────────────────────────────────────┘
                              │
                              ▼
               ┌──────────────────────────────────────┐
               │ 6. Cache Response (if cache enabled) │
               │    Redis SETEX with TTL              │
               └──────────────────────────────────────┘
                              │
                              ▼
               ┌──────────────────────────────────────┐
               │ 7. Return AI Response                │
               └──────────────────────────────────────┘
```

## Fehlerbehandlung (Resilience)

Die Implementierung ist resilient gegenüber Redis-Fehlern:

```python
# Redis-Fehler werden behandelt als Cache-Miss
try:
    cached_value = redis.get(cache_key)
except Exception as e:
    logger.warning(f"Redis GET error: {e}")
    cached_value = None  # Behandeln als Cache-Miss
```

**Verhalten bei Redis-Ausfall:**

1. ✅ Agent-Anfrage schlägt **nicht** fehl
2. ✅ Automatischer Fallback zu normalem AI-Request
3. ✅ Logging für Diagnose (WARNING level)
4. ✅ Kein Caching beim Speichern (wird geloggt, aber ignoriert)

## Verwendungsbeispiele

### Beispiel 1: Agent ohne Cache (Standard)

```yaml
name: simple-agent
provider: OpenAI
model: gpt-4o
# Kein cache-Block → Cache deaktiviert
```

**Verhalten:** Normaler AI-Request bei jeder Anfrage

### Beispiel 2: Agent mit aktiviertem Cache

```yaml
name: cached-agent
provider: OpenAI
model: gpt-4o
cache:
  enabled: true
  ttl_seconds: 3600  # 1 Stunde
  agent_version: 1
```

**Verhalten:**
- Erste Anfrage: AI-Request + Speichern in Redis (1h TTL)
- Folgende Anfragen (gleicher Input): Aus Cache (kein AI-Request)
- Nach 1h: Cache abgelaufen → Neuer AI-Request

### Beispiel 3: Agent-Version Update

```yaml
# Version 1
cache:
  enabled: true
  agent_version: 1  # Cache-Key: ...v1:hash
```

Nach Änderung der Agent-Logik:

```yaml
# Version 2
cache:
  enabled: true
  agent_version: 2  # Cache-Key: ...v2:hash → Neuer Cache!
```

**Vorteil:** Alte gecachte Antworten werden nicht verwendet

## Code-Beispiele

### Python-Code: Agent mit Cache ausführen

```python
from core.services.agents.agent_service import AgentService

# Service initialisieren
agent_service = AgentService()

# Agent ausführen (Cache wird automatisch verwendet wenn konfiguriert)
response = agent_service.execute_agent(
    filename='my-cached-agent.yml',
    input_text='Fasse diesen Text zusammen: ...',
    user=request.user,
    client_ip=request.META.get('REMOTE_ADDR')
)

# response enthält entweder:
# - Gecachte Antwort (wenn Cache-Hit)
# - Frische AI-Antwort (wenn Cache-Miss)
```

### Programmatische Cache-Verwaltung

```python
from core.services.agents.cache import AgentCacheService

# Cache-Service direkt verwenden
cache_service = AgentCacheService()

# Cache-Key generieren
cache_key = cache_service.build_cache_key(
    agent_name='my-agent',
    input_text='Mein Input',
    agent_version=1
)
# Ergebnis: "aiagent:my-agent:v1:a3f5b8c9..."

# Cached Value abrufen
cached_value = cache_service.get(cache_key)

# Value cachen
cache_service.set(cache_key, "Response", ttl_seconds=3600)
```

## Monitoring & Logging

### Log-Messages

**DEBUG-Level** (normale Operation):
```
Cache HIT for key: aiagent:my-agent:v1:abc123...
Cache MISS for key: aiagent:my-agent:v1:def456...
Cached response with key: aiagent:my-agent:v1:ghi789..., TTL: 3600s
```

**INFO-Level** (wichtige Events):
```
Redis cache connection established successfully
Returning cached response for agent 'my-agent'
```

**WARNING-Level** (Fehler):
```
Failed to connect to Redis cache: Connection refused. Cache will be disabled.
Redis GET error for key ...: Connection timeout. Treating as cache miss.
Redis SET error for key ...: Connection lost
```

### Redis-CLI Monitoring

```bash
# Alle AI-Agent Cache-Keys anzeigen
redis-cli KEYS "aiagent:*"

# Cache-Key Details anzeigen
redis-cli GET "aiagent:my-agent:v1:abc123..."

# TTL prüfen
redis-cli TTL "aiagent:my-agent:v1:abc123..."

# Alle Agent-Caches löschen
redis-cli KEYS "aiagent:*" | xargs redis-cli DEL
```

## Tests

### Test-Abdeckung

- ✅ 23 Unit-Tests (Cache-Service)
- ✅ 8 Integrations-Tests (AgentService + Cache)
- ✅ 10 Backward-Compatibility-Tests

### Tests ausführen

```bash
# Alle Cache-Tests
python manage.py test core.services.agents.test_cache

# Integrations-Tests
python manage.py test core.services.agents.test_agent_service.AgentServiceCacheIntegrationTestCase

# Alle Agent-Service-Tests (inkl. Backward Compatibility)
python manage.py test core.services.agents.test_agent_service
```

## Performance & Kosten

### Erwartete Verbesserungen

| Metrik | Ohne Cache | Mit Cache (80% Hit-Rate) |
|--------|------------|--------------------------|
| Response-Zeit | ~2-5s | ~10-50ms (Cache-Hit) |
| AI-Kosten | 100% | ~20% |
| API-Requests | 100% | ~20% |

### Beispiel-Berechnung

```
Szenario: 1000 Requests/Tag, 80% Cache-Hit-Rate

Ohne Cache:
- AI-Requests: 1000
- Kosten (gpt-4o): 1000 × $0.005 = $5.00/Tag
- Response-Zeit: ~3s avg

Mit Cache:
- AI-Requests: 200 (20% miss)
- Cache-Hits: 800 (80%)
- Kosten: 200 × $0.005 = $1.00/Tag
- Ersparnis: $4.00/Tag ($120/Monat)
- Response-Zeit: ~500ms avg (mixed)
```

## Migration bestehender Agenten

### Schritt-für-Schritt Anleitung

1. **Redis einrichten** (falls noch nicht vorhanden)
   ```bash
   # Docker
   docker run -d -p 6379:6379 redis:7-alpine
   
   # Oder: System-Installation
   sudo apt install redis-server
   ```

2. **Environment-Variablen setzen**
   ```bash
   # .env
   REDIS_CACHE_ENABLED=True
   REDIS_CACHE_HOST=localhost
   REDIS_CACHE_PORT=6379
   ```

3. **Agent-YAML erweitern** (optional, pro Agent)
   ```yaml
   # Nur für Agenten, die gecacht werden sollen
   cache:
     enabled: true
     ttl_seconds: 7776000  # 90 Tage
     agent_version: 1
   ```

4. **Testen**
   ```python
   # Ersten Request ausführen (Cache-Miss → AI-Request)
   response1 = agent_service.execute_agent('my-agent.yml', 'Test')
   
   # Zweiten Request ausführen (Cache-Hit → aus Redis)
   response2 = agent_service.execute_agent('my-agent.yml', 'Test')
   
   # response1 == response2 (aber response2 viel schneller)
   ```

### Empfohlene Agenten für Cache

✅ **Gut geeignet:**
- Text-Zusammenfassungen
- Übersetzungen
- Code-Reviews
- Formatierungen
- Standard-Analysen

❌ **Nicht geeignet:**
- Zeit-sensitive Daten
- Personalisierte Antworten
- Zufalls-basierte Generierung
- Kontext-abhängige Dialoge

## Troubleshooting

### Problem: Cache funktioniert nicht

**Lösung:**
1. `REDIS_CACHE_ENABLED=True` in `.env` prüfen
2. `cache.enabled: true` in Agent-YAML prüfen
3. Redis-Verbindung testen: `redis-cli PING`
4. Logs prüfen: `grep -i redis logs/agira.log`

### Problem: Alte Antworten werden verwendet

**Lösung:**
1. Agent-Version erhöhen: `cache.agent_version: 2`
2. Oder: Cache manuell löschen: `redis-cli DEL "aiagent:agent-name:*"`

### Problem: Redis-Fehler in Logs

**Erwartetes Verhalten:**
- Warnings sind OK (Resilienz)
- Agent-Requests funktionieren trotzdem
- Cache wird automatisch deaktiviert bei dauerhaften Fehlern

## Akzeptanzkriterien (erfüllt ✅)

1. ✅ **NoCache-Fallback**: Ohne `cache`-Block werden keine Redis-Operationen ausgeführt
2. ✅ **Hit-Verhalten**: Bei Cache-Hit wird keine KI-Anfrage gestellt
3. ✅ **Miss-Verhalten**: Bei Cache-Miss wird KI angefragt und Antwort gecacht
4. ✅ **Key-Konsistenz**: Gleicher Input + Agent + Version → Gleicher Key
5. ✅ **Keine Kollisionen**: Unterschiedliche Agenten → Unterschiedliche Keys
6. ✅ **Resilienz**: Redis-Ausfall führt nicht zu Request-Fehlern

## Technische Details

### Dateien

```
core/services/agents/
├── cache.py                    # AgentCacheService
├── agent_service.py            # Integration in AgentService
├── test_cache.py               # Unit-Tests
└── test_agent_service.py       # Integrations-Tests

agira/
├── settings.py                 # Redis-Konfiguration
└── .env.example                # Environment-Template

agents/
└── test-cached-agent.yml       # Beispiel-Agent
```

### Dependencies

```
requirements.txt:
redis>=5.0,<6.0  # Neu hinzugefügt
```

### Settings

```python
# agira/settings.py
REDIS_CACHE_ENABLED = os.getenv('REDIS_CACHE_ENABLED', 'False') == 'True'
REDIS_CACHE_HOST = os.getenv('REDIS_CACHE_HOST', 'localhost')
REDIS_CACHE_PORT = int(os.getenv('REDIS_CACHE_PORT', '6379'))
REDIS_CACHE_DB = int(os.getenv('REDIS_CACHE_DB', '0'))
REDIS_CACHE_PASSWORD = os.getenv('REDIS_CACHE_PASSWORD', None)
REDIS_CACHE_SOCKET_TIMEOUT = int(os.getenv('REDIS_CACHE_SOCKET_TIMEOUT', '5'))
REDIS_CACHE_SOCKET_CONNECT_TIMEOUT = int(os.getenv('REDIS_CACHE_SOCKET_CONNECT_TIMEOUT', '5'))
```

## Weiterführende Informationen

- Issue: gdsanger/Agira#[ISSUE_NUMBER]
- Related: gdsanger/Agira#146
- Local Backlog: /items/252/
