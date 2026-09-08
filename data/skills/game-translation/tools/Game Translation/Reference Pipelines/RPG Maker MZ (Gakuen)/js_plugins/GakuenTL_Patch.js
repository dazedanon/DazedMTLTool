//=============================================================================
// GakuenTL_Patch.js
//=============================================================================
/*:
 * @target MZ
 * @plugindesc English patch support - refreshes display text that a save file
 * cached from the build it was made on.
 * @author English translation patch
 *
 * @help GakuenTL_Patch.js
 *
 * A save file stores more than a POSITION. It also stores whatever display
 * text the running build had already copied into a game object, and those
 * copies are never re-read from the data files afterwards. So a save made on
 * the Japanese build keeps showing Japanese in exactly those places, even
 * though the patched data/ beside it is fully English, and no amount of
 * re-translating the data files can reach it.
 *
 * This plugin re-derives those copies whenever a map finishes loading, which
 * covers a fresh transfer, a load, and the reload after a map update.
 *
 * WHAT IT REFRESHES
 *
 *   EventLabel.js sets SIX fields on every Game_Event, once, in
 *   Game_Event.prototype.initialize:
 *
 *       this._labelText   = this.findLabelName();            // <LB:...>
 *       this._labelSize   = param.fontSize || 16;            // plugin param
 *       this._labelX      = findMetaValue(ev, 'LB_X') || 0;  // <LB_X:...>
 *       this._labelY      = findMetaValue(ev, 'LB_Y') || 0;  // <LB_Y:...>
 *       this._labelSwitch = findMetaValue(ev, 'LB_S') || null;
 *       this._labelTail   = findMetaValue(ev, 'LB_T');
 *
 *   Game_Map - including its _events array, and every field on each
 *   Game_Event - is serialised into the save. On load those objects come back
 *   with whatever the SAVING build gave them and initialize() never runs
 *   again, so ALL SIX are frozen at their pre-patch values.
 *
 *   Refreshing only `_labelText` is not enough, and the difference is visible:
 *   a save carried `_labelSize: 22` from an earlier build of this patch and
 *   `_labelX: 0`, so the captions rendered at the wrong size and the ones
 *   nudged away from a map edge by `<LB_X:>` stayed clipped - even though the
 *   note tags in data/ were correct. Every field set at init has to be
 *   re-derived, not just the obvious one.
 *
 *   The derivations below deliberately re-invoke the plugin's OWN helpers -
 *   `findLabelName()` and `PluginManagerEx.findMetaValue()` - rather than
 *   reimplementing them, so this cannot drift from what EventLabel does. Only
 *   `fontSize` is read separately, from `PluginManager.parameters`, because
 *   the plugin keeps its parsed copy in a closure.
 *
 *   Safe because every one of these is derived from data the patch owns and
 *   none of them is a key: the tag NAMES are untouched, and this game issues
 *   no EventLabel plugin command, so no event ever sets a label at runtime
 *   for this to clobber.
 *
 * WHAT IT DELIBERATELY DOES NOT TOUCH
 *
 *   Anything that doubles as a KEY. Re-deriving a value that some other system
 *   looks up by name would send an old save to a target its own build never
 *   had. Only fields that are purely drawn are refreshed here.
 *
 *   Game_Interpreter._list, the cached command list of an event that was
 *   RUNNING when the player saved. Those few commands replay from the cache
 *   until that one event ends, and then everything after it comes from the
 *   patched files. Rewriting a running interpreter's command list is not worth
 *   the risk of moving the index it is pointing at.
 *
 * No parameters, no plugin commands. Load it LAST, after EventLabel.
 */

(() => {
    'use strict';

    const refreshEventLabels = function() {
        if (typeof $gameMap === 'undefined' || !$gameMap) {
            return;
        }
        // Only act when EventLabel is actually present.
        if (typeof Game_Event.prototype.findLabelName !== 'function') {
            return;
        }
        // The plugin keeps its parsed parameters in a closure, so read the
        // same registered value rather than guessing a number.
        let fontSize = 0;
        try {
            fontSize = Number(PluginManager.parameters('EventLabel').fontSize);
        } catch (e) {
            fontSize = 0;
        }
        const meta = (typeof PluginManagerEx !== 'undefined'
                      && PluginManagerEx
                      && typeof PluginManagerEx.findMetaValue === 'function')
            ? PluginManagerEx.findMetaValue.bind(PluginManagerEx)
            : null;

        const events = $gameMap.events ? $gameMap.events() : [];
        for (let i = 0; i < events.length; i++) {
            const ev = events[i];
            if (!ev || typeof ev.findLabelName !== 'function') {
                continue;
            }
            try {
                // `event()` is $dataMap.events[id]; if the map data is not
                // loaded for this event, leave the cached values alone.
                if (!ev.event || !ev.event()) {
                    continue;
                }
                const data = ev.event();
                const text = ev.findLabelName();
                if (text !== undefined) {
                    ev._labelText = text;
                }
                if (fontSize) {
                    ev._labelSize = fontSize;
                }
                if (meta) {
                    ev._labelX = meta(data, 'LB_X') || 0;
                    ev._labelY = meta(data, 'LB_Y') || 0;
                    ev._labelSwitch = meta(data, 'LB_S') || null;
                    ev._labelTail = meta(data, 'LB_T');
                }
            } catch (e) {
                // One bad event must not stop the rest, and must never stop
                // the map from loading.
                console.warn('GakuenTL_Patch: could not refresh a label', e);
            }
        }
        // `_tileEvents` holds the same Game_Event instances that `events()`
        // returned, so it is already refreshed - but rebuild it anyway in case
        // a plugin replaced the objects rather than filtering them.
        if (typeof $gameMap.refreshTileEvents === 'function') {
            $gameMap.refreshTileEvents();
        }
    };

    const _Scene_Map_onMapLoaded = Scene_Map.prototype.onMapLoaded;
    Scene_Map.prototype.onMapLoaded = function() {
        _Scene_Map_onMapLoaded.apply(this, arguments);
        refreshEventLabels();
    };
})();
