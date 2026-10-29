"""Serveur MCP (Model Context Protocol — Streamable HTTP / JSON-RPC 2.0) pour Tacite.

Expose tous les outils de `agent_tools.REGISTRY`, l'outil `doctrine` et la ressource
`tacite://doctrine` sur `/mcp` et `/api/mcp` afin que Cursor puisse interroger et piloter
Tacite directement comme Gorgone ou Acheron.
"""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse

from .database import SessionLocal
from .services import agent_tools

log = logging.getLogger("tacite.mcp")

router = APIRouter()

DOCTRINE_PATH = Path(__file__).resolve().parent / "doctrine.md"

MCP_INSTRUCTIONS = (
    "Tacite — plateforme de Press Intelligence et de recommandation d'influence. "
    "Lisez la doctrine (`doctrine` tool ou ressource `tacite://doctrine`) avant de rédiger une analyse de fond. "
    "Outils clés : `topic_brief` (analyse complète d'un sujet : cadrage, anomalies éditoriales, tradecraft ICD 203, dynamique OTAN ABCDE, risques client et journalistes à contacter), "
    "`who_covers` et `approach_angle` (qui approcher et avec quel angle), `dashboard` (synthèse du jour), "
    "`list_outlets` / `get_outlet` / `compare_outlets`, `list_journalists` / `get_journalist`, `search_articles`, `topics`, `generate_report`. "
    "Toute note ou rapport demandé par l'utilisateur se fait avec `press_note` : cinq blocs fixes (reading, frames, evidence, effects, lever) et le design Tacite, déjà appliqués au PDF. "
    "Le bloc lever contient le tableau des journalistes : passez `journalists` (influence_targets ou who_covers) et `topic`. "
    "L'absence de dossier client n'ôte pas ce tableau. N'écrivez jamais qu'aucun client n'est engagé pour refuser la liste. "
    "Enregistrez l'URL renvoyée telle quelle. Interdit d'écrire le HTML, le CSS, ou d'imprimer un PDF soi-même. "
    "Les outils d'écriture (modification, suppression, lancement de tâche) demandent `confirm: true` — demandez toujours confirmation à l'utilisateur avant d'appeler avec `confirm: true`."
)


def _read_doctrine() -> str:
    try:
        return DOCTRINE_PATH.read_text(encoding="utf-8")
    except Exception:
        return "# TACITE — PRESS INTELLIGENCE ANALYTICAL DOCTRINE\n"


_NETWORK_TOOLS = {"fetch_url", "google_news", "gdelt"}


def _annotations(name: str, kind: str) -> dict:
    """Cursor classe un outil sans readOnlyHint dans le groupe « écriture ».
    Sans cette annotation, la liste s'affiche à 0 outil de lecture activé."""
    write = kind == "write"
    return {
        "title": name.replace("_", " "),
        "readOnlyHint": not write,
        "destructiveHint": write,
        "idempotentHint": not write,
        "openWorldHint": name in _NETWORK_TOOLS,
    }


def _mcp_tools_list() -> list[dict]:
    tools: list[dict] = [
        {
            "name": "doctrine",
            "description": "Renvoie la Doctrine Analytique de Renseignement Presse de Tacite (McCombs & Shaw / Entman, Tradecraft ODNI ICD 203 / Heuer, OTAN ABCDE, anomalies éditoriales et leviers d'action client). À lire avant toute analyse approfondie.",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            "annotations": _annotations("doctrine", "read"),
        }
    ]
    for name, (spec, _fn, kind) in agent_tools.REGISTRY.items():
        if name == "render_chart":
            # Utile uniquement dans l'UI chat interne de Tacite
            continue
        schema = copy.deepcopy(spec.get("parameters") or {"type": "object", "properties": {}})
        if schema.get("type") != "object":
            schema["type"] = "object"
        schema.setdefault("properties", {})
        desc = spec.get("description") or ""
        if kind == "write":
            props = dict(schema.get("properties") or {})
            props["confirm"] = {
                "type": "boolean",
                "description": "Mettre à true uniquement après confirmation explicite de l'utilisateur pour appliquer l'écriture en base.",
                "default": False,
            }
            schema["properties"] = props
            desc = f"[ÉCRITURE] {desc} (Passer confirm=true après accord de l'utilisateur pour appliquer)."
        tools.append({
            "name": name,
            "description": desc,
            "inputSchema": schema,
            "annotations": _annotations(name, kind),
        })
    return tools


def _call_mcp_tool(name: str, arguments: dict) -> tuple[bool, Any]:
    if name == "doctrine":
        return False, _read_doctrine()
    if name not in agent_tools.REGISTRY:
        return True, {"error": f"Outil Tacite inconnu : {name}"}

    _spec, _fn, kind = agent_tools.REGISTRY[name]
    db = SessionLocal()
    try:
        args = dict(arguments or {})
        confirm = bool(args.pop("confirm", False))
        if kind == "write":
            desc = agent_tools.describe_write(name, args, db)
            if not confirm:
                return False, {
                    "status": "confirmation_required",
                    "description": desc,
                    "instruction": "Demandez confirmation à l'utilisateur, puis rappelez cet outil avec `confirm: true` pour appliquer le changement.",
                }
            res = agent_tools.apply_write(name, db, args)
            return False, {"status": "applied", "description": desc, **res}

        ctx: dict = {"conversation_id": None, "parts": []}
        res = agent_tools.run(name, db, args, ctx)
        return False, res
    except Exception as e:  # noqa: BLE001
        db.rollback()
        log.exception("MCP tool %s failed", name)
        return True, {"error": f"{type(e).__name__}: {e}"}
    finally:
        db.close()


def _handle_rpc_message(msg: dict) -> dict | None:
    method = msg.get("method")
    msg_id = msg.get("id")
    params = msg.get("params") or {}

    # Notifications JSON-RPC (pas d'id) -> aucune réponse attendue
    if msg_id is None:
        return None

    if method == "initialize":
        client_Version = params.get("protocolVersion") or "2024-11-05"
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": client_Version,
                "capabilities": {
                    "tools": {"listChanged": False},
                    "resources": {"subscribe": False, "listChanged": False},
                    "prompts": {"listChanged": False},
                },
                "serverInfo": {
                    "name": "tacite",
                    "version": "1.0.0",
                },
                "instructions": MCP_INSTRUCTIONS,
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"tools": _mcp_tools_list()},
        }

    if method == "tools/call":
        tname = params.get("name") or ""
        targs = params.get("arguments") or {}
        is_err, payload = _call_mcp_tool(tname, targs)
        text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, default=str, indent=2)
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "content": [{"type": "text", "text": text}],
                "isError": is_err,
            },
        }

    if method == "resources/list":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "resources": [
                    {
                        "uri": "tacite://doctrine",
                        "name": "Tacite — Press Intelligence Analytical Doctrine",
                        "description": "Doctrine méthodologique complète de Tacite (McCombs & Shaw, Entman, ODNI ICD 203, OTAN ABCDE).",
                        "mimeType": "text/markdown",
                    }
                ]
            },
        }

    if method == "resources/read":
        uri = params.get("uri") or ""
        if uri == "tacite://doctrine":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "contents": [
                        {
                            "uri": "tacite://doctrine",
                            "mimeType": "text/markdown",
                            "text": _read_doctrine(),
                        }
                    ]
                },
            }
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32602, "message": f"Ressource inconnue : {uri}"},
        }

    if method == "prompts/list":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "prompts": [
                    {
                        "name": "press_intelligence_brief",
                        "description": "Analyse un sujet d'actualité selon la Doctrine de Renseignement Presse Tacite (5 blocs exécutifs).",
                        "arguments": [
                            {"name": "topic", "description": "Sujet ou événement à analyser", "required": True},
                            {"name": "country", "description": "Code pays ISO-2 optionnel (FR, DE, GB…)", "required": False},
                        ],
                    }
                ]
            },
        }

    if method == "prompts/get":
        pname = params.get("name")
        pargs = params.get("arguments") or {}
        topic = pargs.get("topic") or "actualité"
        country = pargs.get("country") or ""
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "description": f"Brief Press Intelligence sur {topic}",
                "messages": [
                    {
                        "role": "user",
                        "content": {
                            "type": "text",
                            "text": (
                                f"Appelle `doctrine` puis `topic_brief` sur le sujet « {topic} »"
                                + (f" (pays={country})" if country else "")
                                + " puis `press_note` (pas de HTML, pas de PDF local) avec reading, figures, frames, evidence, effects, lever, "
                                + "journalists=influence_targets et topic. Le tableau des journalistes est obligatoire, même sans dossier client."
                            ),
                        },
                    }
                ],
            },
        }

    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def _wants_sse(request: Request) -> bool:
    return "text/event-stream" in (request.headers.get("accept") or "")


def _sse_response(messages: list[dict]) -> StreamingResponse:
    def gen():
        for msg in messages:
            payload = json.dumps(msg, ensure_ascii=False, default=str)
            yield f"event: message\ndata: {payload}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@router.get("/mcp")
@router.get("/api/mcp")
async def mcp_get(request: Request):
    """Info endpoint. Un GET SSE sans session est refusé : le serveur est sans état."""
    if _wants_sse(request):
        return JSONResponse(
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Method Not Allowed"}},
            status_code=405,
        )
    return {
        "name": "tacite",
        "version": "1.0.0",
        "protocol": "mcp-streamable-http",
        "endpoint": str(request.base_url).rstrip("/") + request.url.path,
        "tools_count": len(_mcp_tools_list()),
        "resources": ["tacite://doctrine"],
    }


@router.post("/mcp")
@router.post("/api/mcp")
async def mcp_post(request: Request):
    """Endpoint MCP Streamable HTTP (JSON-RPC 2.0 simple ou batch).

    Cursor envoie ``Accept: application/json, text/event-stream`` et lit la
    réponse comme un flux SSE (``event: message``), comme Acheron et Gorgone.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
            status_code=400,
        )

    sse = _wants_sse(request)

    if isinstance(body, list):
        responses = []
        for item in body:
            if isinstance(item, dict):
                r = await run_in_threadpool(_handle_rpc_message, item)
                if r is not None:
                    responses.append(r)
        if not responses:
            return Response(status_code=202)
        return _sse_response(responses) if sse else JSONResponse(responses)

    if isinstance(body, dict):
        resp = await run_in_threadpool(_handle_rpc_message, body)
        if resp is None:
            return Response(status_code=202)
        return _sse_response([resp]) if sse else JSONResponse(resp)

    return JSONResponse(
        {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}},
        status_code=400,
    )
