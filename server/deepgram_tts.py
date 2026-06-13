"""Deepgram TTS with a `speed` (speaking-rate) control.

Pipecat's `DeepgramTTSService` (1.2.x) builds the `/v1/speak` WebSocket URL from
a fixed set of query params (`model`, `encoding`, `sample_rate`, `mip_opt_out`)
and exposes no hook for Deepgram's `speed` voice control
(https://developers.deepgram.com/docs/tts-voice-controls — speaking-rate
multiplier, 0.7–1.5, default 1.0, not billed).

`SpeedDeepgramTTSService` overrides `_connect_websocket` to append `&speed=` when
a speed is set. The override mirrors the upstream method verbatim except for that
one appended param; revisit if the pinned pipecat version changes.
"""

from __future__ import annotations

from loguru import logger
from pipecat.frames.frames import ErrorFrame
from pipecat.services.deepgram.tts import DeepgramTTSService
from websockets.asyncio.client import connect as websocket_connect
from websockets.protocol import State


class SpeedDeepgramTTSService(DeepgramTTSService):
    def __init__(self, *args, speed: float | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._speed = speed

    async def _connect_websocket(self):
        """Connect to Deepgram WebSocket API, adding `speed` when configured."""
        try:
            if self._websocket and self._websocket.state is State.OPEN:
                return

            logger.debug("Connecting to Deepgram WebSocket")

            # Build WebSocket URL with query parameters
            params = []
            params.append(f"model={self._settings.voice}")
            params.append(f"encoding={self._encoding}")
            params.append(f"sample_rate={self.sample_rate}")
            if self._mip_opt_out is not None:
                params.append(f"mip_opt_out={str(self._mip_opt_out).lower()}")
            if self._speed is not None:
                params.append(f"speed={self._speed}")

            url = f"{self._base_url}/v1/speak?{'&'.join(params)}"

            headers = {"Authorization": f"Token {self._api_key}"}

            websocket = await websocket_connect(url, additional_headers=headers)
            self._websocket = websocket

            response_headers = websocket.response.headers if websocket.response else {}
            headers = {k: v for k, v in response_headers.items() if k.startswith("dg-")}
            logger.debug(f'{self}: Websocket connection initialized: {{"headers": {headers}}}')

            await self._call_event_handler("on_connected")
        except Exception as e:
            logger.error(f"{self} exception: {e}")
            await self.push_error_frame(ErrorFrame(error=f"{self} error: {e}"))
            self._websocket = None
            await self._call_event_handler("on_connection_error", f"{e}")
