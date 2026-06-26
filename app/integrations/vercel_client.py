"""
vercel_client — bajar la fuente de un deploy y crear deploys preview en Vercel.

La landing (`automiq-landing-astro`, Astro) se deploya por CLI, sin repo git: la
fuente de verdad es el último deploy de producción. Este cliente:
  1. download_source(): reconstruye la fuente del último deploy de prod en un dir.
  2. deploy(): sube ese dir como deploy PREVIEW (o prod si se pide) con la CLI de
     Vercel y devuelve la URL.

Lo usa el agente web_optimizer: baja la fuente → la mejora con Claude Code →
deploya un preview → avisa a Discord para que el humano apruebe a producción.
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from ..config import Settings
from ..log import get_logger

log = get_logger("vercel")

_API = "https://api.vercel.com"


class VercelError(RuntimeError):
    pass


class VercelClient:
    def __init__(self, settings: Settings):
        self.s = settings
        self.token = settings.vercel_token
        self.team = settings.vercel_team_id or ""
        self.project = settings.vercel_project or ""

    # ── helpers HTTP ──
    def _headers(self) -> Dict[str, str]:
        if not self.token:
            raise VercelError("falta VERCEL_TOKEN")
        return {"Authorization": f"Bearer {self.token}"}

    def _params(self, extra: Optional[dict] = None) -> dict:
        p = {"teamId": self.team} if self.team else {}
        if extra:
            p.update(extra)
        return p

    def _get(self, path: str, params: Optional[dict] = None, raw: bool = False):
        with httpx.Client(timeout=60) as c:
            r = c.get(f"{_API}{path}", headers=self._headers(), params=self._params(params))
        if r.status_code >= 400:
            raise VercelError(f"GET {path} -> {r.status_code}: {r.text[:200]}")
        return r.content if raw else r.json()

    # ── deploy de prod más reciente ──
    def latest_production_deployment(self) -> Dict[str, Any]:
        data = self._get(
            "/v6/deployments",
            {"projectId": self.project, "target": "production", "state": "READY", "limit": 1},
        )
        deps = data.get("deployments", [])
        if not deps:
            raise VercelError("no hay deploy de producción READY")
        return deps[0]

    # ── descarga de la fuente ──
    def download_source(self, deployment_id: str, dest: str) -> int:
        """Reconstruye la fuente del deploy en `dest`. Devuelve la cantidad de archivos.
        Salta artefactos de build/deps (node_modules, dist, .vercel, .astro)."""
        tree = self._get(f"/v6/deployments/{deployment_id}/files")
        nodes = tree if isinstance(tree, list) else tree.get("files", [])
        # Saltar artefactos de build/deps/caché EN CUALQUIER nivel (el deploy a veces
        # los anida bajo un dir 'src/').
        skip = {"node_modules", "dist", ".vercel", ".astro", ".git", ".vscode"}
        count = 0
        for node in nodes:
            count += self._walk_download(deployment_id, node, Path(dest), skip)
        log.info("vercel_source_downloaded", deployment=deployment_id, files=count, dest=dest)
        return count

    def _walk_download(self, dep: str, node: Dict[str, Any], base: Path, skip: set) -> int:
        name = node.get("name", "")
        ntype = node.get("type")
        if name in skip:
            return 0
        if ntype == "directory":
            sub = base / name
            n = 0
            for child in node.get("children", []) or []:
                n += self._walk_download(dep, child, sub, skip)
            return n
        # archivo
        uid = node.get("uid")
        if not uid:
            return 0
        target = base / name
        target.parent.mkdir(parents=True, exist_ok=True)
        content = self._get(f"/v7/deployments/{dep}/files/{uid}", raw=True)
        data = self._decode_file(content)
        target.write_bytes(data)
        return 1

    @staticmethod
    def find_project_root(dest: str) -> str:
        """Devuelve el dir que contiene el proyecto (astro.config.* o package.json).
        El deploy suele envolver la fuente en un subdir 'src/'."""
        base = Path(dest)
        markers = ("astro.config.mjs", "astro.config.ts", "astro.config.js", "package.json")
        # Búsqueda por amplitud: el root más superficial que tenga un marker.
        candidates = sorted(
            (p.parent for m in markers for p in base.rglob(m)),
            key=lambda d: len(d.parts),
        )
        return str(candidates[0]) if candidates else str(base)

    @staticmethod
    def _decode_file(content: bytes) -> bytes:
        """El endpoint puede devolver el archivo crudo o un JSON {data: base64}."""
        try:
            obj = json.loads(content)
            if isinstance(obj, dict) and "data" in obj:
                try:
                    return base64.b64decode(obj["data"])
                except Exception:
                    return str(obj["data"]).encode("utf-8")
        except (json.JSONDecodeError, ValueError):
            pass
        return content

    # ── deploy preview/prod vía CLI ──
    def deploy(self, source_dir: str, prod: bool = False) -> str:
        """Deploya `source_dir` a Vercel con la CLI. Devuelve la URL del deploy.
        prod=False (default) → PREVIEW; prod=True → producción."""
        if not self.token:
            raise VercelError("falta VERCEL_TOKEN")
        # Asegurar el link al proyecto correcto (.vercel/project.json).
        self._ensure_project_link(source_dir)
        cmd = ["vercel", "deploy", "--yes", "--token", self.token]
        if self.team:
            cmd += ["--scope", self.team]
        if prod:
            cmd.append("--prod")
        try:
            proc = subprocess.run(
                cmd, cwd=source_dir, capture_output=True, text=True, timeout=900,
            )
        except subprocess.TimeoutExpired as e:
            raise VercelError("timeout deployando en Vercel") from e
        out = (proc.stdout or "") + "\n" + (proc.stderr or "")
        if proc.returncode != 0:
            raise VercelError(f"vercel deploy falló (exit {proc.returncode}): {out[-300:]}")
        url = self._extract_url(out)
        if not url:
            raise VercelError(f"no pude extraer la URL del deploy: {out[-200:]}")
        log.info("vercel_deployed", prod=prod, url=url)
        return url

    def _ensure_project_link(self, source_dir: str) -> None:
        if not self.project:
            return
        vdir = Path(source_dir) / ".vercel"
        vdir.mkdir(exist_ok=True)
        (vdir / "project.json").write_text(
            json.dumps({"projectId": self.project, "orgId": self.team}),
            encoding="utf-8",
        )

    @staticmethod
    def _extract_url(out: str) -> str:
        # La CLI imprime líneas tipo "https://<deploy>.vercel.app"
        urls = re.findall(r"https://[a-zA-Z0-9._-]+\.vercel\.app", out)
        return urls[-1] if urls else ""


def get_vercel_client(settings: Settings) -> VercelClient:
    return VercelClient(settings)
