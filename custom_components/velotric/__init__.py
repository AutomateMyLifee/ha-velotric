"""Velotric E-Bike integration for Home Assistant."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN
from .coordinator import VelotricCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Velotric from a config entry."""
    mac = entry.data.get("mac")
    
    coordinator = VelotricCoordinator(hass, entry, mac=mac)
    
    if not await coordinator._async_setup():
        raise ConfigEntryNotReady("Failed to connect to Velotric bike")
    
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator
    
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])
    
    # Register services
    async def handle_force_update(call: ServiceCall):
        """Force an immediate update."""
        await coordinator.async_request_refresh()
    
    async def handle_send_query(call: ServiceCall):
        """Send a specific query to the bike."""
        query_type = call.data.get("query_type")
        if query_type:
            await coordinator.ble_client.query(query_type)
    
    hass.services.async_register(DOMAIN, "force_update", handle_force_update)
    hass.services.async_register(DOMAIN, "send_query", handle_send_query)
    
    # Listen for options updates
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update without full reload."""
    coordinator: VelotricCoordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.async_update_options()
    # Trigger a refresh with new settings
    await coordinator.async_request_refresh()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: VelotricCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
    await coordinator.async_shutdown()
    
    return await hass.config_entries.async_unload_platforms(entry, ["sensor"])