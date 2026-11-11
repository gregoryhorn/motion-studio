"""Dashboard metadata only. No technical records, files, media or model API."""
from fastapi import APIRouter

router = APIRouter()


@router.get('/capabilities')
def capabilities():
    return dict(surface='dashboard-metadata', native_surface='desktop/plugin.js',
        technical_access='unconfigured', inference='unverified-unavailable',
        private_media='unavailable', native_creation='unavailable', production='not-implemented',
        audience='Gateway-authorized session controllers, including operators and multiple clients; not exclusive-owner or LOCAL-only proof.')
