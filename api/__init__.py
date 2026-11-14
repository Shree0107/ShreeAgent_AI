"""HTTP + WebSocket API over the analysis engine (FastAPI). The React app in web/ is its client.

Layers: data/ (providers, cache) -> analysis/, signals/, forecasting/ (engine) -> api/ (this) -> web/ (UI).
"""
