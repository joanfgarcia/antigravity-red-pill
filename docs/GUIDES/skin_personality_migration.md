# MIGRATION: Lore Skin Personality Field (v5.6.2)

## What changed

All Lore Skins in `lore_skins.yaml` now include a `personality` field that defines the agent's first-person voice when operating under that skin. Previously only 3 skins had this field (`her`, `enterprise_core`, `wintermute`). Now all 15 skins are consistent.

## Action required for existing installations

The `personality` field lives in the YAML file and is automatically available when you switch skins. To refresh your active skin's stored engram in Qdrant with the new personality data, simply re-apply your current skin:

```bash
# Re-apply whichever skin you are currently using:
red-pill mode cyberpunk
red-pill mode matrix
red-pill mode wintermute
# etc.
```

This will overwrite the stored `directive_memories` engram with the full updated skin data including `personality`.

## Default skin change

Fresh installations (`red-pill seed`) now use `enterprise_core` as the default active skin instead of `cyberpunk`. Existing installations are unaffected.
