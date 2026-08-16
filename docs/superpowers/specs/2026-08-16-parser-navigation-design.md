# Parser Navigation Design

## Problem

Scribity has a dedicated Parser view, but the persistent header navigation has no Parser tab. The view is only discoverable through the create menu's **Import DRR Report** command, so users can enter it but cannot return to it through the same navigation used for Library, Inspector, Draft, Render, and Sources.

## Design

Add one **Parser** button to the existing header tab group immediately after **Sources**. The button will follow the same markup, spacing, typography, click behavior, and inactive styling as the other tabs. When the Parser view is active, the button will use the orange accent already associated with DRR importing.

The existing **Import DRR Report** create-menu command will remain unchanged because it is useful as an action-oriented entry point. The new tab provides persistent wayfinding; it does not replace or duplicate any parsing logic.

## Alternatives Considered

- Rename the tab **Import**. This is more action-oriented but does not match the internal view name or the punch-list terminology.
- Move the create-menu command into the header without adding a tab. This would make import easier to find but would not show the current location or provide consistent return navigation.
- Add the **Parser** tab. This is the smallest change and matches the existing navigation model. This is the selected approach.

## Scope and Safety

Only the header navigation in `dashboard.html` will change. Parser state, file selection, parsing, importing, saving, and document loading will not change. Existing uncommitted work in `dashboard.html`, `scribity_server.py`, and `test_scribity_server.py` will be preserved.

The main UI risk is reduced horizontal space in the header. Scribity is a desktop-oriented interface, and the added label is short. Verification will confirm the tab renders in the current desktop layout and that clicking it activates the existing Parser view.

## Verification

- Confirm the Parser tab is absent before the change and present afterward.
- Confirm clicking **Parser** displays **DRR Report Import** and applies the active orange styling.
- Confirm another tab can still be selected afterward.
- Run the existing automated checks and a whitespace/error scan without using or modifying the user's document files.
