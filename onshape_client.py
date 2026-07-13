"""
Onshape API client for converting proprietary CAD formats (.sldprt, .catpart, .sldasm)
to STEP via the Onshape cloud translation service.

Workflow:
  1. Upload file to Onshape → creates a document with imported Part Studio
  2. Poll translation status until complete
  3. Export the Part Studio as STEP
  4. Download STEP to local temp path
  5. Return temp STEP path for B-Rep analysis
"""

import os
import time
import base64
import hashlib
import hmac
import urllib.parse
from datetime import datetime, timezone
from typing import Optional

import httpx

ONSHAPE_BASE = "https://cad.onshape.com/api"


class OnshapeClient:
    """Zero-dependency Onshape REST API client with HMAC signing."""

    def __init__(self, access_key: str, secret_key: str):
        self.access_key = access_key
        self.secret_key = secret_key.encode("utf-8")
        self._http = httpx.Client(timeout=120)

    # ── HMAC request signing ──────────────────────────────────────────

    def _sign(self, method: str, path: str, date: str, content_type: str = "", body: bytes = b"") -> str:
        """Generate Onshape HMAC-SHA256 Authorization header value."""
        parts = [
            method.upper(),
            "",
            content_type,
            date,
            path,
        ]
        string_to_sign = "\n".join(parts)
        sig = hmac.new(self.secret_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"On {self.access_key}:HmacSHA256:{sig}"

    def _headers(self, method: str, path: str, content_type: str = "", body: bytes = b"") -> dict:
        date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        return {
            "Date": date,
            "Authorization": self._sign(method, path, date, content_type, body),
            "Content-Type": content_type or "application/json",
            "Accept": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        url = f"{ONSHAPE_BASE}{path}" if path.startswith("/") else f"{ONSHAPE_BASE}/{path}"
        ct = kwargs.pop("content_type", "")
        body = kwargs.pop("body", b"")
        headers = self._headers(method, path, ct, body)
        resp = self._http.request(method, url, headers=headers, **kwargs)
        resp.raise_for_status()
        return resp

    # ── Import ────────────────────────────────────────────────────────

    def upload_and_import(self, file_path: str) -> dict:
        """
        Upload a CAD file (.sldprt, .catpart, .sldasm, etc.) to Onshape.
        Returns the translation object with id, documentId, etc.
        """
        filename = os.path.basename(file_path)
        ext = os.path.splitext(filename)[1].lower()

        # Map extensions to Onshape format names
        format_map = {
            ".sldprt": "solidworks",
            ".sldasm": "solidworks",
            ".catpart": "catia",
            ".catproduct": "catia",
            ".prt": "proe",
            ".asm": "proe",
            ".ipt": "inventor",
            ".3dm": "rhino",
        }
        onshape_format = format_map.get(ext, ext.lstrip("."))

        with open(file_path, "rb") as f:
            file_data = f.read()

        path = "/documents/files"

        # Build multipart form data
        boundary = f"----WebKitFormBoundary{int(time.time() * 1000)}"
        body_parts = []

        # File part
        body_parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode())
        body_parts.append(file_data)
        body_parts.append(b"\r\n")

        # element tab name
        body_parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="elementName"\r\n\r\n{os.path.splitext(filename)[0]}\r\n'.encode())

        # encode as directory
        body_parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="encode"\r\n\r\ntrue\r\n'.encode())

        # owner - will be set from the API key's account
        body_parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="owner"\r\n\r\n\r\n'.encode())

        body_parts.append(f'--{boundary}--\r\n'.encode())
        body = b"".join(body_parts)

        ct = f"multipart/form-data; boundary={boundary}"
        resp = self._request("POST", path, content_type=ct, body=body, content=None)
        data = resp.json()

        # The response may contain translation info
        if isinstance(data, list) and len(data) > 0:
            return data[0]
        return data

    def get_translation(self, translation_id: str) -> dict:
        """Poll translation status."""
        path = f"/translations/{translation_id}"
        resp = self._request("GET", path)
        return resp.json()

    def wait_for_translation(self, translation_id: str, timeout: int = 300, poll_interval: float = 2.0) -> dict:
        """Block until translation completes or times out."""
        start = time.time()
        while time.time() - start < timeout:
            status = self.get_translation(translation_id)
            state = status.get("status", "")
            if state == "done":
                return status
            elif state == "failed":
                raise RuntimeError(f"Onshape translation failed: {status}")
            time.sleep(poll_interval)
        raise TimeoutError(f"Onshape translation timed out after {timeout}s")

    # ── Export as STEP ────────────────────────────────────────────────

    def export_as_step(self, document_id: str, workspace_id: str, element_id: str) -> str:
        """
        Export a Part Studio as STEP file. Returns the STEP file content.
        Uses the async translation endpoint.
        """
        path = f"/asynchronous/translations"

        body = {
            "formatName": "STEP",
            "clientId": "",
            "documentId": document_id,
            "workspaceId": workspace_id,
            "elementId": element_id,
            "linkDocumentId": document_id,
        }

        resp = self._request("POST", path, json=body)
        data = resp.json()

        # Wait for export translation
        translation_id = data.get("id")
        if translation_id:
            result = self.wait_for_translation(translation_id)
            # Download the result
            url = result.get("resultExternalData", [None])
            if url and isinstance(url, list) and len(url) > 0:
                dl_resp = self._http.get(url[0])
                dl_resp.raise_for_status()
                return dl_resp.content
            elif "url" in result:
                dl_resp = self._http.get(result["url"])
                dl_resp.raise_for_status()
                return dl_resp.content

        raise RuntimeError(f"Failed to export STEP: {data}")

    # ── High-level: convert file to STEP ──────────────────────────────

    def convert_to_step(self, file_path: str, output_step_path: str) -> str:
        """
        Convert a proprietary CAD file to STEP via Onshape.
        Returns the path to the downloaded STEP file.
        """
        print(f"[Onshape] Uploading {os.path.basename(file_path)}...")
        translation = self.upload_and_import(file_path)

        # Extract document info from translation
        doc_id = translation.get("documentId")
        wvm = translation.get("workspaceId") or translation.get("versionId") or translation.get("microversionId")
        element_id = translation.get("elementId")

        if not doc_id:
            # Poll for completion if translation is async
            translation_id = translation.get("id")
            if translation_id:
                print(f"[Onshape] Waiting for import translation {translation_id}...")
                translation = self.wait_for_translation(translation_id)
                doc_id = translation.get("documentId")
                wvm = translation.get("workspaceId") or translation.get("versionId")
                element_id = translation.get("elementId")

        if not doc_id:
            raise RuntimeError(f"Could not get document ID from import: {translation}")

        # Get the part studio element if not provided
        if not element_id:
            element_id = self._find_part_studio(doc_id, wvm)

        print(f"[Onshape] Document {doc_id}, exporting as STEP...")
        step_content = self.export_as_step(doc_id, wvm, element_id)

        with open(output_step_path, "wb") as f:
            f.write(step_content)

        print(f"[Onshape] STEP saved to {output_step_path}")

        # Cleanup: delete the temporary Onshape document
        try:
            self._delete_document(doc_id)
        except Exception:
            pass  # Best effort cleanup

        return output_step_path

    def _find_part_studio(self, document_id: str, workspace_id: str) -> str:
        """Find the first Part Studio element in a document."""
        path = f"/documents/{document_id}/workspaces/{workspace_id}/elements"
        resp = self._request("GET", path)
        elements = resp.json()
        for el in elements:
            if el.get("type") == "PARTS Studio":
                return el["id"]
        # Fallback: return first element
        if elements:
            return elements[0]["id"]
        raise RuntimeError("No Part Studio found in imported document")

    def _delete_document(self, document_id: str):
        """Delete a temporary Onshape document."""
        path = f"/documents/{document_id}"
        try:
            self._request("DELETE", path)
        except Exception:
            pass


def convert_cad_via_onshape(file_path: str, output_step_path: str) -> str:
    """
    Convenience function. Reads ONSHAPE_ACCESS_KEY and ONSHAPE_SECRET_KEY
    from environment (or .env file), converts the file, returns STEP path.
    """
    # Try to load from .env if python-dotenv is available
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    access_key = os.environ.get("ONSHAPE_ACCESS_KEY", "")
    secret_key = os.environ.get("ONSHAPE_SECRET_KEY", "")

    if not access_key or not secret_key:
        raise RuntimeError(
            "Onshape API keys not configured. "
            "Set ONSHAPE_ACCESS_KEY and ONSHAPE_SECRET_KEY in .env or environment."
        )

    client = OnshapeClient(access_key, secret_key)
    return client.convert_to_step(file_path, output_step_path)
