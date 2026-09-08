/* QA only. Load after the shipped MZ engine, never as a release plugin.
 * Explicitly checks engine-caught errors and frame progress; an IPC reply is insufficient.
 * Does not override focus, scheduling, gameplay or saves.
 */
(function(root) {
  'use strict';
  function create(env = root) {
    const delay = ms => new Promise(resolve => env.setTimeout(resolve, ms));
    function snapshot() {
      const graphics = env.Graphics, manager = env.SceneManager;
      if (!graphics || !manager || !Number.isFinite(graphics.frameCount)) throw new Error('MZ engine is not ready');
      return {frame: graphics.frameCount, engineError: graphics._errorPrinter?.textContent || '',
        tickerStarted: graphics.app?.ticker?.started ?? graphics._app?.ticker?.started ?? null,
        scene: manager._scene?.constructor?.name || null, map: env.$gameMap?.mapId?.() ?? null,
        hidden: env.document?.hidden ?? null, focused: env.document?.hasFocus?.() ?? null};
    }
    function assertHealthy() {
      const state = snapshot();
      if (state.engineError) throw new Error('MZ caught an engine error: ' + state.engineError);
      if (state.tickerStarted === false) throw new Error('MZ ticker is stopped: ' + JSON.stringify(state));
      return state;
    }
    async function assertAdvancing(milliseconds = 250) {
      if (!Number.isFinite(milliseconds) || milliseconds <= 0) throw new Error('Invalid observation interval');
      const before = assertHealthy(); await delay(milliseconds); const after = assertHealthy();
      if (after.frame <= before.frame) throw new Error('MZ frames did not advance: ' + JSON.stringify({before, after}));
      return {before, after};
    }
    async function waitFor(predicate, {timeout = 10000, poll = 50, label = 'native consumer'} = {}) {
      if (typeof predicate !== 'function' || !Number.isFinite(timeout) || timeout <= 0 || !Number.isFinite(poll) || poll <= 0) throw new Error('Invalid wait options');
      const end = Date.now() + timeout;
      do {
        assertHealthy();
        if (predicate()) {
          const progress = await assertAdvancing(Math.min(250, timeout));
          if (predicate()) return progress;
        }
        await delay(poll);
      } while (Date.now() < end);
      throw new Error('Timed out waiting for ' + label + ': ' + JSON.stringify(snapshot()));
    }
    return {snapshot, assertHealthy, assertAdvancing, waitFor};
  }
  root.GameTranslationMZHealth = create(root);
  if (typeof module !== 'undefined' && module.exports) module.exports = {create};
})(globalThis);
