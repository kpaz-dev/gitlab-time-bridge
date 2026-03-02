GitLab → Teamwork Time Sync (FastAPI)

Herramienta ligera en Python/FastAPI para sincronizar automáticamente el tiempo imputado en Issues de GitLab hacia Teamwork Time Tracking mediante su API.

Estructura del proyecto

gitlab_time_bridge/
├── app/
│   ├── main.py                # Servidor FastAPI (uvicorn app.main:app)
│   ├── config.py              # Configuración vía variables de entorno
│   ├── routes/
│   │   └── webhook.py         # Endpoint POST /webhook/gitlab
│   ├── services/
│   │   ├── gitlab_service.py  # Utilidades para extraer datos del evento
│   │   └── teamwork_service.py# Integración con Teamwork (stub + dry-run)
│   ├── parsers/
│   │   └── time_parser.py     # Parser "added 1h/30m of time spent" → segundos
│   └── models/
│       └── event_models.py    # Modelos Pydantic mínimos para eventos
│
├── tests/
│   └── sample_payloads/
│       └── gitlab_note_time.json # Ejemplo de payload GitLab (note con tiempo)
├── requirements.txt
├── Dockerfile
└── README.md

Requisitos

- Python >= 3.11
- FastAPI, Uvicorn, httpx, Pydantic (incluidos en requirements.txt)

Variables de entorno (config)

- GITLAB_WEBHOOK_SECRET: Token secreto para validar el webhook (cabecera X-Gitlab-Token). Opcional pero recomendado.
- TEAMWORK_BASE_URL: Base URL de Teamwork. Ej: https://miempresa.teamwork.com
- TEAMWORK_API_TOKEN: Token de API de Teamwork. Si no se define, el modo dry-run queda activo y no se harán llamadas reales.
- TEAMWORK_DRY_RUN: true/false. Por defecto true si no hay token. En true solo se registran logs sin llamar a la API.
- TEAMWORK_PROJECT_MAP_JSON: Mapa JSON para resolver el proyecto de Teamwork a partir del proyecto de GitLab. Admite keys como id de proyecto de GitLab ("123") o path con namespace ("pilma/pilma-suite"). También se puede definir una key "default".
  Ejemplo: {"123": "99999", "pilma/pilma-suite": "99999", "default": "99999"}
- TEAMWORK_USER_MAP_JSON: Mapa JSON para convertir usuario GitLab → userId de Teamwork. Se buscan coincidencias por id, username o nombre. Ej: {"42": "111", "jperez": "111", "Juan Perez": "111"}
- TEAMWORK_TASKLIST_ID: ID de la Task List de Teamwork donde se crearán automáticamente las tareas para cada Issue de GitLab (si se reciben eventos de issue). Ej: 2244612.
- TEAMWORK_CREATE_TASK_ON_NOTE: true/false. Si true (por defecto), si llega una nota con tiempo y aún no existe la tarea en Teamwork, se intentará crear primero la tarea y luego registrar el tiempo contra ella.

Fichero .env

Además de exportar variables en tu shell, puedes crearlas en un fichero .env en la raíz del proyecto (se cargará gracias a python-dotenv al ejecutar con uvicorn o al usar herramientas que lean .env). Ya tienes un .env.example con placeholders. Cópialo así:

```
cp .env.example .env
```

Luego edita .env y ajusta valores (tokens, mapas, etc.).

Ejecutar en local

1) Crear y activar entorno, instalar dependencias:

```
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2) Exportar variables de entorno mínimas (ejemplo):

```
export GITLAB_WEBHOOK_SECRET="mi-secreto"
export TEAMWORK_BASE_URL="https://miempresa.teamwork.com"
export TEAMWORK_API_TOKEN="TW_TOKEN"   # opcional; si no, queda en dry-run
export TEAMWORK_PROJECT_MAP_JSON='{"pilma/pilma-suite": "99999", "default": "99999"}'
export TEAMWORK_USER_MAP_JSON='{"jperez": "111"}'
export TEAMWORK_TASKLIST_ID="2244612"
export TEAMWORK_CREATE_TASK_ON_NOTE=true
```

3) Iniciar servidor:

```
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

4) Probar con el payload de ejemplo:

```
curl -X POST \
  http://localhost:8000/webhook/gitlab \
  -H 'Content-Type: application/json' \
  -H 'X-Gitlab-Token: mi-secreto' \
  --data @tests/sample_payloads/gitlab_note_time.json
```

Si TEAMWORK_DRY_RUN=true o no hay TEAMWORK_API_TOKEN, verás en logs lo que "se enviaría" a Teamwork.

Configurar Webhook en GitLab

- URL: http://<HOST>:8000/webhook/gitlab
- Secret Token: usar el valor de GITLAB_WEBHOOK_SECRET
- Events: Notes (al menos). Esta app ignora tipos distintos a object_kind = "note".

Qué hace el endpoint

- Valida el secreto del webhook (si está configurado).
- Acepta el payload de GitLab.
- Si object_kind != "note" → ignora.
- Busca mensajes tipo: "added 1h of time spent", "added 30m of time spent", o combinaciones "1h 30m".
- Extrae título del issue, id del issue, proyecto, usuario y segundos.
- Convierte el tiempo a segundos y lo envía a Teamwork usando TeamworkService (si no está en dry-run).
- Si `object_kind = "issue"` con acción de creación (open/opened), crea (o reaprovecha si existe) una tarea en la Task List indicada por `TEAMWORK_TASKLIST_ID`, usando como título `[GL#<iid>] <título del issue>` y como descripción la del issue + enlace.
- Si `object_kind = "note"` con tiempo y existe `TEAMWORK_TASKLIST_ID`, buscará/creará la tarea correspondiente y registrará el tiempo contra esa tarea (en lugar de a nivel de proyecto).

Docker

Construir imagen:

```
docker build -t gitlab-time-bridge:latest .
```

Ejecutar contenedor:

```
docker run --rm -p 8000:8000 \
  -e GITLAB_WEBHOOK_SECRET=mi-secreto \
  -e TEAMWORK_BASE_URL=https://miempresa.teamwork.com \
  -e TEAMWORK_API_TOKEN=TW_TOKEN \
  -e TEAMWORK_PROJECT_MAP_JSON='{"pilma/pilma-suite": "99999", "default": "99999"}' \
  -e TEAMWORK_USER_MAP_JSON='{"jperez": "111"}' \
  -e TEAMWORK_TASKLIST_ID=2244612 \
  -e TEAMWORK_CREATE_TASK_ON_NOTE=true \
  gitlab-time-bridge:latest
```

Notas

- Por defecto el servicio opera en modo dry-run si no hay token; útil para probar sin impactar Teamwork.
- El endpoint está pensado para GitLab Self-Managed como en tu red interna (ej.: http://10.45.5.2/pilma/pilma-suite/-/issues).
- La integración con Teamwork usa httpx de forma asíncrona; el método actual es un stub preparado para producción, pero puede requerir ajustar la ruta exacta del endpoint y el formato del payload según tu versión de la API de Teamwork.
 - La creación/búsqueda de tareas usa un enfoque simple: se lista la Task List y se busca por título exacto. Si necesitas reglas distintas (por ejemplo, buscar por referencia externa o crear en distintas listas según el proyecto), se puede ampliar.