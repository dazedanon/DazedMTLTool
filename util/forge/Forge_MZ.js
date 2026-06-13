//=============================================================================
// Forge_MZ.js  —  In-game cheat & editor overlay for RPG Maker MZ
//=============================================================================
/*:
 * @target MZ
 * @plugindesc Forge — modern in-game editor: variables, switches, items, actors, gold, teleport, common events, freeze/lock & battle cheats. (MZ)
 * @author len
 * @url https://gitgud.io/zero64801/forge-mvmz
 *
 * @param hotkey
 * @text Toggle Hotkey
 * @desc Key to toggle the panel.
 * @type string
 * @default F10
 *
 * @param speedKey
 * @text Speedhack Key
 * @desc Key to toggle fast-forward (e.g. Control, Shift, Alt, or a letter).
 * @type string
 * @default Control
 *
 * @param startOpen
 * @text Open on start
 * @desc Open the panel automatically on new game / load.
 * @type boolean
 * @default false
 *
 * @param itemMaxOverride
 * @text Item "Max" value
 * @desc Value used by the "Max" button for item stacks (0 = use engine maxItems).
 * @type number
 * @min 0
 * @default 0
 *
 * @param uiScale
 * @text UI Scale
 * @desc Overlay size. Use auto to match game width, or a number like 1.5 or 2.
 * @type string
 * @default auto
 *
 * @command open
 * @text Open / Toggle Panel
 * @desc Toggle the Forge overlay.
 *
 * @help
 * Forge — drop-in cheat & editor for RPG Maker MZ.
 * Place in js/plugins/ and enable in the Plugin Manager. Press F10 to open.
 *
 * Sections: Variables · Switches · Items/Weapons/Armors · Actors · Party/Gold ·
 * Map/Teleport · Common Events · Data Lock (freeze) · Battle cheats.
 *
 * All edits are RAM-only and never written to save files. No external requests.
 * Plugin command "Open / Toggle Panel" toggles the overlay from events.
 *
 * Credits: len — https://gitgud.io/zero64801/forge-mvmz
 */

/* ===================================================================================
 * Forge — in-game cheat & editor overlay for RPG Maker MV / MZ   (shared core)
 * Clean-room reimplementation of MTool's variable/value editor. Vanilla JS, zero deps.
 * This file is the engine-agnostic core; the MV/MZ ship files prepend the plugin header.
 * Layers:  ops (DOM-free, testable) · locks (prototype monkeypatches) · cheats · ui (Shadow DOM)
 * =================================================================================== */
(function (root) {
  'use strict';
  if (root && root.__FORGE_CORE__) return;

  // ---------- environment ----------
  var IS_MZ = (typeof Utils !== 'undefined' && Utils.RPGMAKER_NAME === 'MZ');
  var nodeFs = null, nodePath = null;
  try { if (typeof require === 'function') { nodeFs = require('fs'); nodePath = require('path'); } } catch (e) {}
  function gameCwd() { try { return process.cwd(); } catch (e) { return '.'; } }

  var PARAM_NAMES = ['Max HP', 'Max MP', 'Attack', 'Defense', 'M.Attack', 'M.Defense', 'Agility', 'Luck'];

  // ---------- small utils ----------
  function clampInt(v, lo, hi) { v = Math.floor(Number(v) || 0); if (v < lo) v = lo; if (hi != null && v > hi) v = hi; return v; }
  function defined(x) { return typeof x !== 'undefined' && x !== null; }
  function dataName(d) { return d && d.name ? d.name : ''; }
  // actor.level may be a getter (number), a method, or only the _level field across engines/plugins.
  function actorLevel(a) { if (!a) return 0; if (typeof a.level === 'number') return a.level; if (typeof a.level === 'function') return a.level(); return a._level || 1; }

  // ===================================================================================
  // OPS — pure logic, only touches $game*/$data* globals. Unit-testable.
  // ===================================================================================
  var ops = {};

  ops.vars = {
    count: function () { return defined(window.$dataSystem) ? $dataSystem.variables.length - 1 : 0; },
    name: function (id) { return (defined(window.$dataSystem) && $dataSystem.variables[id]) || ('Variable ' + id); },
    get: function (id) { return defined(window.$gameVariables) ? $gameVariables.value(id) : 0; },
    set: function (id, v) { if (!defined(window.$gameVariables)) return; $gameVariables.setValue(id, typeof v === 'string' && v.trim() !== '' && !isNaN(v) ? Number(v) : v); },
    list: function () {
      var out = [], n = this.count();
      for (var id = 1; id <= n; id++) out.push({ id: id, name: this.name(id), value: this.get(id) });
      return out;
    }
  };

  ops.switches = {
    count: function () { return defined(window.$dataSystem) ? $dataSystem.switches.length - 1 : 0; },
    name: function (id) { return (defined(window.$dataSystem) && $dataSystem.switches[id]) || ('Switch ' + id); },
    get: function (id) { return defined(window.$gameSwitches) ? $gameSwitches.value(id) : false; },
    set: function (id, v) { if (!defined(window.$gameSwitches)) return; $gameSwitches.setValue(id, !!v); },
    toggle: function (id) { this.set(id, !this.get(id)); },
    list: function () {
      var out = [], n = this.count();
      for (var id = 1; id <= n; id++) out.push({ id: id, name: this.name(id), value: this.get(id) });
      return out;
    }
  };

  var INV_TABLES = { item: '$dataItems', weapon: '$dataWeapons', armor: '$dataArmors' };
  ops.inv = {
    table: function (kind) { return window[INV_TABLES[kind]] || []; },
    data: function (kind, id) { return this.table(kind)[id] || null; },
    count: function (kind, id) { var d = this.data(kind, id); return d && defined(window.$gameParty) ? $gameParty.numItems(d) : 0; },
    maxStack: function (kind, id) { if (MTC._itemMaxOverride > 0) return MTC._itemMaxOverride; var d = this.data(kind, id); return d && defined(window.$gameParty) ? $gameParty.maxItems(d) : 99; },
    grant: function (kind, id, n) { var d = this.data(kind, id); if (d && defined(window.$gameParty)) $gameParty.gainItem(d, n, false); if (locks.isItemFrozen(kind, id)) LOCK.items.set(itemKey(kind, id), { kind: kind, id: id, value: this.count(kind, id) }); },
    setCount: function (kind, id, target) { this.grant(kind, id, clampInt(target, 0, null) - this.count(kind, id)); },
    max: function (kind, id) { this.setCount(kind, id, this.maxStack(kind, id)); },
    list: function (kind) {
      var t = this.table(kind), out = [];
      for (var id = 1; id < t.length; id++) {
        var d = t[id]; if (!d || !d.name) continue;
        out.push({ id: id, name: d.name, description: d.description || '', iconIndex: d.iconIndex || 0, count: $gameParty.numItems(d) });
      }
      return out;
    }
  };

  ops.gold = {
    get: function () { return defined(window.$gameParty) ? $gameParty.gold() : 0; },
    max: function () { return defined(window.$gameParty) && $gameParty.maxGold ? $gameParty.maxGold() : 99999999; },
    add: function (n) {
      if (!defined(window.$gameParty)) return;
      if (LOCK.gold != null) { LOCK.gold = clampInt(LOCK.gold + n, 0, this.max()); (locks._origGainGold || $gameParty.gainGold).call($gameParty, LOCK.gold - $gameParty.gold()); return; }
      if (n >= 0) $gameParty.gainGold(n); else $gameParty.loseGold(-n);
    },
    set: function (target) { this.add(clampInt(target, 0, this.max()) - this.get()); }
  };

  ops.actors = {
    list: function () {
      var out = [];
      if (!defined(window.$dataActors)) return out;
      for (var id = 1; id < $dataActors.length; id++) {
        var d = $dataActors[id]; if (!d) continue;
        var a = $gameActors.actor(id);
        out.push({ id: id, name: a ? a.name() : d.name, level: a ? actorLevel(a) : (d.initialLevel || 1), inParty: $gameParty._actors ? $gameParty._actors.indexOf(id) >= 0 : false });
      }
      return out;
    },
    get: function (id) {
      var a = $gameActors.actor(id); if (!a) return null;
      var params = [];
      for (var p = 0; p < 8; p++) params.push({ id: p, name: PARAM_NAMES[p], value: a.param(p) });
      var skills = [];
      if (defined(window.$dataSkills)) for (var s = 1; s < $dataSkills.length; s++) { var sk = $dataSkills[s]; if (sk && sk.name) skills.push({ id: s, name: sk.name, learned: a.isLearnedSkill ? a.isLearnedSkill(s) : (a.skills().indexOf(sk) >= 0) }); }
      var equips = [], slots = a.equipSlots ? a.equipSlots() : [], cur = a.equips();
      for (var e = 0; e < slots.length; e++) equips.push({ slot: e, etypeId: slots[e], current: cur[e] ? cur[e].name : '(none)' });
      return {
        id: id, name: a.name(), level: actorLevel(a), exp: a.currentExp ? a.currentExp() : 0,
        nextExp: a.nextLevelExp ? a.nextLevelExp() : 0,
        hp: a.hp, mp: a.mp, tp: a.tp, mhp: a.mhp, mmp: a.mmp,
        params: params, skills: skills, equips: equips,
        inParty: $gameParty._actors ? $gameParty._actors.indexOf(id) >= 0 : false
      };
    },
    setLevel: function (id, lv) { var a = $gameActors.actor(id); if (a) { var cap = a.maxLevel ? a.maxLevel() : 99; a.changeLevel(clampInt(lv, 1, cap), false); a.refresh(); } },
    setExp: function (id, exp) { var a = $gameActors.actor(id); if (a) { a.changeExp(clampInt(exp, 0, null), false); a.refresh(); } },
    setHp: function (id, v) { var a = $gameActors.actor(id); if (a) { a.setHp(clampInt(v, 0, a.mhp)); a.refresh(); } },
    setMp: function (id, v) { var a = $gameActors.actor(id); if (a) { a.setMp(clampInt(v, 0, a.mmp)); a.refresh(); } },
    setTp: function (id, v) { var a = $gameActors.actor(id); if (a && a.setTp) { a.setTp(clampInt(v, 0, 100)); a.refresh(); } },
    addParam: function (id, pid, delta) { var a = $gameActors.actor(id); if (a) { a.addParam(pid, Math.floor(delta)); a.refresh(); } },
    // param(pid) = round((paramBase+paramPlus) * paramRate * paramBuffRate) clamped to [paramMin,paramMax].
    // addParam only mutates paramPlus, so invert the rate to land the *visible* param on target.
    setParam: function (id, pid, target) {
      var a = $gameActors.actor(id); if (!a) return;
      var rate = (a.paramRate ? a.paramRate(pid) : 1) * (a.paramBuffRate ? a.paramBuffRate(pid) : 1) || 1;
      var cap = a.paramMax ? a.paramMax(pid) : null;
      var want = clampInt(target, a.paramMin ? a.paramMin(pid) : 0, cap);
      var base = a.paramBase ? a.paramBase(pid) : 0, plus = (a.paramPlus ? a.paramPlus(pid) : (a._paramPlus ? a._paramPlus[pid] : 0)) || 0;
      a.addParam(pid, Math.round(want / rate) - base - plus);
      a.refresh();
    },
    learn: function (id, skillId) { var a = $gameActors.actor(id); if (a) a.learnSkill(skillId); },
    forget: function (id, skillId) { var a = $gameActors.actor(id); if (a) a.forgetSkill(skillId); },
    equip: function (id, slotId, kind, itemId) { var a = $gameActors.actor(id); if (!a) return; var item = itemId ? ops.inv.data(kind, itemId) : null; if (a.forceChangeEquip) a.forceChangeEquip(slotId, item); else a.changeEquip(slotId, item); a.refresh(); },
    recover: function (id) { var a = $gameActors.actor(id); if (a) { a.recoverAll(); a.refresh(); } },
    setName: function (id, name) { var a = $gameActors.actor(id); if (a) a.setName(String(name)); },
    addToParty: function (id) { $gameParty.addActor(id); },
    removeFromParty: function (id) { $gameParty.removeActor(id); }
  };

  ops.party = {
    members: function () { return defined(window.$gameParty) ? $gameParty.members().map(function (a) { return { id: a.actorId(), name: a.name(), level: actorLevel(a) }; }) : []; },
    add: function (id) { if (defined(window.$gameParty)) $gameParty.addActor(id); },
    remove: function (id) { if (defined(window.$gameParty)) $gameParty.removeActor(id); },
    steps: function () { return defined(window.$gameParty) ? $gameParty.steps() : 0; },
    // RPG Maker derives playtime from frame count (Game_System has no playtime()).
    playtime: function () { return (typeof Graphics !== 'undefined' && Graphics.frameCount) ? Math.floor(Graphics.frameCount / 60) : 0; }
  };

  ops.map = {
    list: function () {
      var out = [];
      if (!defined(window.$dataMapInfos)) return out;
      for (var id = 1; id < $dataMapInfos.length; id++) { var m = $dataMapInfos[id]; if (m) out.push({ id: id, name: m.name || ('Map ' + id) }); }
      return out;
    },
    current: function () { if (!defined(window.$gameMap) || !defined(window.$gamePlayer)) return { mapId: 0, x: 0, y: 0, dir: 2 }; return { mapId: $gameMap.mapId(), x: $gamePlayer.x, y: $gamePlayer.y, dir: $gamePlayer.direction ? $gamePlayer.direction() : 2 }; },
    teleport: function (mapId, x, y, dir, fade) { $gamePlayer.reserveTransfer(mapId, clampInt(x, 0, null), clampInt(y, 0, null), dir || 0, fade == null ? 0 : fade); },
    loadMapFile: function (mapId) {
      if (!nodeFs) return null;
      try { var f = 'Map' + String(mapId).padStart(3, '0') + '.json'; return JSON.parse(nodeFs.readFileSync(nodePath.join(gameCwd(), 'data', f), 'utf8')); }
      catch (e) { return null; }
    },
    noclip: function (b) { locks.state.noclip = !!b; if (defined(window.$gamePlayer)) $gamePlayer.setThrough(!!b); },
    isNoclip: function () { return !!locks.state.noclip; },
    speed: function (n) { if (defined(window.$gamePlayer)) $gamePlayer.setMoveSpeed(clampInt(n, 1, 8)); }
  };

  ops.commonev = {
    list: function () {
      var out = [];
      if (!defined(window.$dataCommonEvents)) return out;
      for (var id = 1; id < $dataCommonEvents.length; id++) { var c = $dataCommonEvents[id]; if (c) out.push({ id: id, name: c.name || ('Common Event ' + id) }); }
      return out;
    },
    run: function (id) { if (defined(window.$gameTemp)) $gameTemp.reserveCommonEvent(id); }
  };

  ops.battle = {
    inBattle: function () {
      if (typeof SceneManager === 'undefined' || !SceneManager._scene) return false;
      if (typeof Scene_Battle !== 'undefined' && SceneManager._scene instanceof Scene_Battle) return true;
      var c = SceneManager._scene.constructor;                       // fallback if class binding unavailable
      return !!(c && c.name === 'Scene_Battle');
    },
    instantWin: function () {
      if (typeof $gameTroop === 'undefined' || !$gameTroop) return;
      $gameTroop.members().forEach(function (e) {
        e.setHp(0);
        if (e.deathStateId && e.addState) e.addState(e.deathStateId());   // mark actually dead
        else if (e.die) e.die();
        if (e.performCollapse) e.performCollapse();                       // visual collapse
        e.refresh();
      });
      if (typeof BattleManager !== 'undefined' && BattleManager.checkBattleEnd) BattleManager.checkBattleEnd();
    },
    flee: function () { if (typeof BattleManager !== 'undefined' && BattleManager.processAbort) BattleManager.processAbort(); }
  };

  // ===================================================================================
  // LOCKS — prototype-level monkeypatches + per-frame re-assertion. Installed once.
  // ===================================================================================
  var LOCK = { vars: new Map(), switches: new Map(), items: new Map(), gold: null, stats: new Map(), noclip: false };
  function itemKey(kind, id) { return kind + ':' + id; }

  var locks = {
    state: LOCK,
    _installed: false,
    install: function () {
      if (this._installed) return; this._installed = true;
      // Variables
      if (typeof Game_Variables !== 'undefined') {
        var _sv = Game_Variables.prototype.setValue;
        Game_Variables.prototype.setValue = function (id, value) { if (LOCK.vars.has(id)) value = LOCK.vars.get(id); _sv.call(this, id, value); };
      }
      // Switches
      if (typeof Game_Switches !== 'undefined') {
        var _ss = Game_Switches.prototype.setValue;
        Game_Switches.prototype.setValue = function (id, value) { if (LOCK.switches.has(id)) value = LOCK.switches.get(id); _ss.call(this, id, value); };
      }
      // Gold: substitute (not block) so freezeGold can re-snapshot on edit; item freeze is tick-based
      // (NOT a gainItem block) so equip bookkeeping / give-take still runs, corrected next frame.
      if (typeof Game_Party !== 'undefined') {
        var _gg = Game_Party.prototype.gainGold;
        locks._origGainGold = _gg;
        Game_Party.prototype.gainGold = function (n) { if (LOCK.gold != null) return; _gg.call(this, n); };
      }
      // Battle: god mode + OHKO via one executeHpDamage override
      if (typeof Game_Action !== 'undefined') {
        var _ehd = Game_Action.prototype.executeHpDamage;
        Game_Action.prototype.executeHpDamage = function (target, value) {
          if (CHEAT.god && target.isActor && target.isActor() && value > 0) value = 0;
          if (CHEAT.ohko && this.subject().isActor && this.subject().isActor() && target.isEnemy && target.isEnemy()) value = target.hp;
          _ehd.call(this, target, value);
        };
      }
      // God mode also blocks non-action HP loss for actors (slip/regen, event Change-HP) + floor damage.
      if (typeof Game_Battler !== 'undefined' && Game_Battler.prototype.gainHp) {
        var _gh = Game_Battler.prototype.gainHp;
        Game_Battler.prototype.gainHp = function (value) { if (CHEAT.god && this.isActor && this.isActor() && value < 0) value = 0; _gh.call(this, value); };
      }
      if (typeof Game_Actor !== 'undefined' && Game_Actor.prototype.executeFloorDamage) {
        var _efd = Game_Actor.prototype.executeFloorDamage;
        Game_Actor.prototype.executeFloorDamage = function () { if (CHEAT.god) return; _efd.call(this); };
      }
      // No encounters
      if (typeof Game_Player !== 'undefined') {
        var _epv = Game_Player.prototype.encounterProgressValue;
        Game_Player.prototype.encounterProgressValue = function () { return CHEAT.noEncounter ? 0 : _epv.call(this); };
      }
      // Speedhack: drive the scene update extra times per frame (speed>1) or skip frames (speed<1).
      // Input is still read once per real frame, so the whole game (movement, anim, battle, messages,
      // events, timers) runs faster/slower. Works for MV and MZ (both expose SceneManager.updateScene).
      if (typeof SceneManager !== 'undefined' && SceneManager.updateScene) {
        var _updateScene = SceneManager.updateScene, _spdAcc = 0;
        // Extra updates are only safe in a steady scene: the scene must be started, not changing, and
        // (on a map) not mid-transfer — otherwise $dataMap is briefly null and the scroll code throws.
        function speedSafe(mgr) {
          if (mgr.isCurrentSceneStarted) { if (!mgr.isCurrentSceneStarted()) return false; }          // MV
          else if (mgr._scene && mgr._scene.isStarted) { if (!mgr._scene.isStarted()) return false; }  // MZ
          if (mgr.isSceneChanging && mgr.isSceneChanging()) return false;                              // mid scene transition
          if (typeof $gamePlayer !== 'undefined' && $gamePlayer && $gamePlayer.isTransferring && $gamePlayer.isTransferring()) return false;
          if (typeof DataManager !== 'undefined' && DataManager.isMapLoaded && !DataManager.isMapLoaded()) return false; // map (re)loading
          return true;
        }
        SceneManager.updateScene = function () {
          var sp = CHEAT.speed || 1;
          if (sp >= 1) {
            _updateScene.call(this);
            if (sp > 1 && this._scene && typeof this._scene.update === 'function' && speedSafe(this)) {
              _spdAcc += (sp - 1);
              var guard = 0;
              while (_spdAcc >= 1 && guard++ < 64) { _spdAcc -= 1; try { this._scene.update(); } catch (e) { _spdAcc = 0; break; } }
            } else { _spdAcc = 0; }   // not safe / not boosting -> don't bank up a burst of catch-up updates
          } else {
            _spdAcc += sp;
            if (_spdAcc >= 1) { _spdAcc -= 1; _updateScene.call(this); }
            else if (this._scene) {                       // skip the game advance this frame, keep start/ready bookkeeping
              var u = this._scene.update; this._scene.update = function () {};
              try { _updateScene.call(this); } finally { this._scene.update = u; }
            }
          }
        };
      }
      // Clear stale freeze snapshots when the engine swaps in fresh game objects (new game / load).
      if (typeof DataManager !== 'undefined') {
        if (DataManager.setupNewGame) { var _sng = DataManager.setupNewGame; DataManager.setupNewGame = function () { locks.clearAll(); _sng.call(this); }; }
        if (DataManager.extractSaveContents) { var _esc = DataManager.extractSaveContents; DataManager.extractSaveContents = function (c) { locks.clearAll(); return _esc.call(this, c); }; }
      }
    },
    // Freeze setters update both the lock map and the live value once. Maps store parsed objects so
    // the per-frame tick never re-parses string keys.
    freezeVar: function (id, on) { if (on) { LOCK.vars.set(id, ops.vars.get(id)); ops.vars.set(id, ops.vars.get(id)); } else LOCK.vars.delete(id); },
    freezeSwitch: function (id, on) { if (on) LOCK.switches.set(id, ops.switches.get(id)); else LOCK.switches.delete(id); },
    freezeItem: function (kind, id, on) { var k = itemKey(kind, id); if (on) LOCK.items.set(k, { kind: kind, id: id, value: ops.inv.count(kind, id) }); else LOCK.items.delete(k); },
    freezeGold: function (on) { LOCK.gold = on ? ops.gold.get() : null; },
    freezeStat: function (actorId, stat, on) { var k = actorId + ':' + stat; if (on) { var a = defined(window.$gameActors) ? $gameActors.actor(actorId) : null; LOCK.stats.set(k, { actorId: actorId, stat: stat, value: a ? a[stat] : 0 }); } else LOCK.stats.delete(k); },
    isVarFrozen: function (id) { return LOCK.vars.has(id); },
    isSwitchFrozen: function (id) { return LOCK.switches.has(id); },
    isItemFrozen: function (kind, id) { return LOCK.items.has(itemKey(kind, id)); },
    isStatFrozen: function (actorId, stat) { return LOCK.stats.has(actorId + ':' + stat); },
    // Per-frame: re-assert values the overrides can't catch (hp/mp/tp, gold target, item counts, noclip).
    tick: function () {
      if (!LOCK.noclip && LOCK.gold == null && !LOCK.stats.size && !LOCK.items.size) return;   // early-out
      if (LOCK.noclip && defined(window.$gamePlayer) && !$gamePlayer.isThrough()) $gamePlayer.setThrough(true);
      if (LOCK.gold != null && defined(window.$gameParty) && $gameParty.gold() !== LOCK.gold) (locks._origGainGold || $gameParty.gainGold).call($gameParty, LOCK.gold - $gameParty.gold());
      if (LOCK.stats.size && defined(window.$gameActors)) {
        LOCK.stats.forEach(function (e) {
          var a = $gameActors.actor(e.actorId); if (!a) return;
          if (e.stat === 'hp' && a.hp !== e.value) a.setHp(Math.min(e.value, a.mhp));
          else if (e.stat === 'mp' && a.mp !== e.value) a.setMp(Math.min(e.value, a.mmp));
          else if (e.stat === 'tp' && a.tp !== e.value && a.setTp) a.setTp(e.value);
        });
      }
      if (LOCK.items.size && defined(window.$gameParty)) {
        LOCK.items.forEach(function (e) { if (ops.inv.count(e.kind, e.id) !== e.value) { var d = ops.inv.data(e.kind, e.id); if (d) $gameParty.gainItem(d, e.value - ops.inv.count(e.kind, e.id), false); } });
      }
    },
    summary: function () {
      var out = [];
      LOCK.vars.forEach(function (v, id) { out.push({ type: 'var', id: id, label: 'Var ' + id + ' · ' + ops.vars.name(id), value: v }); });
      LOCK.switches.forEach(function (v, id) { out.push({ type: 'switch', id: id, label: 'Switch ' + id + ' · ' + ops.switches.name(id), value: v ? 'ON' : 'OFF' }); });
      LOCK.items.forEach(function (e, key) { out.push({ type: 'item', key: key, label: e.kind + ' ' + e.id + ' · ' + (ops.inv.data(e.kind, e.id) ? ops.inv.data(e.kind, e.id).name : ''), value: e.value }); });
      LOCK.stats.forEach(function (e, key) { out.push({ type: 'stat', key: key, label: 'Actor ' + e.actorId + ' · ' + e.stat.toUpperCase(), value: e.value }); });
      if (LOCK.gold != null) out.push({ type: 'gold', label: 'Gold (frozen)', value: LOCK.gold });
      if (LOCK.noclip) out.push({ type: 'noclip', label: 'Noclip (active)', value: 'ON' });
      return out;
    },
    clearAll: function () { LOCK.vars.clear(); LOCK.switches.clear(); LOCK.items.clear(); LOCK.stats.clear(); LOCK.gold = null; if (LOCK.noclip) ops.map.noclip(false); }
  };

  // ===================================================================================
  // CHEATS — global toggles consumed by the lock overrides + battle actions.
  // ===================================================================================
  var CHEAT = { god: false, ohko: false, noEncounter: false, speed: 1, uiFocused: false };
  var cheats = {
    state: CHEAT,
    setGod: function (b) { CHEAT.god = !!b; },
    setOhko: function (b) { CHEAT.ohko = !!b; },
    setNoEncounter: function (b) { CHEAT.noEncounter = !!b; },
    setSpeed: function (n) { CHEAT.speed = Math.max(0.1, Math.min(Number(n) || 1, 16)); },
    toggleSpeed: function () { this.setSpeed(CHEAT.speed !== 1 ? 1 : (MTC._speedBoost || 2)); return CHEAT.speed; },
    instantWin: function () { ops.battle.instantWin(); },
    flee: function () { ops.battle.flee(); }
  };

  // expose the assembled API (UI is attached below if a real DOM is present)
  var MTC = { env: { IS_MZ: IS_MZ }, ops: ops, locks: locks, cheats: cheats, LOCK: LOCK, CHEAT: CHEAT, PARAM_NAMES: PARAM_NAMES, _itemMaxOverride: 0, _hotkey: 'F10', _speedKey: 'Control', _speedBoost: 2, _uiScale: 'auto' };
  if (root) { root.Forge = MTC; root.__FORGE_CORE__ = true; }
  if (typeof module !== 'undefined' && module.exports) module.exports = MTC;

  // ---- engine boot hooks (guarded; only when classes exist) ----
  if (typeof Scene_Base !== 'undefined') {
    var _su = Scene_Base.prototype.update;
    Scene_Base.prototype.update = function () { _su.call(this); try { locks.tick(); } catch (e) {} };
  }
  // install lock overrides as soon as the game classes are available
  try { locks.install(); } catch (e) {}

  // ---- UI: attach only when a real browser DOM is available (skipped in Node tests) ----
  if (typeof document !== 'undefined' && document.body && typeof document.body.attachShadow === 'function' && typeof window !== 'undefined') {
    try { MTC.ui = buildUI(MTC); } catch (e) { try { console.error('[Forge] UI init failed', e); } catch (_) {} }
  }

  // ===================================================================================
  // UI — Shadow-DOM overlay. Inlined so the single ship file works with zero deps.
  // ===================================================================================
  function buildUI(API) {
    var LS = 'forge:';
    function store(k, v) { try { localStorage.setItem(LS + k, JSON.stringify(v)); } catch (e) {} }
    function load(k, d) { try { var s = localStorage.getItem(LS + k); return s == null ? d : JSON.parse(s); } catch (e) { return d; } }
    function resolveUiScale(v) {
      if (v !== 'auto' && v != null && String(v).trim() !== '') {
        var n = parseFloat(v);
        if (!isNaN(n) && n > 0) return Math.max(0.75, Math.min(3, n));
      }
      var base = 816;
      var gameW = (typeof Graphics !== 'undefined' && Graphics.width) ? Graphics.width : 0;
      var viewW = window.innerWidth || document.documentElement.clientWidth || base;
      var w = Math.max(gameW || base, viewW);
      var scale = w / base;
      var dpr = window.devicePixelRatio || 1;
      if (dpr > 1.15) scale *= Math.min(2, 0.75 + dpr * 0.35);
      return Math.max(1, Math.min(2.75, scale));
    }
    function scalePx(n, fx) {
      if (!fx || fx === 1) return n;
      return Math.round(n * fx);
    }
    function scalePxCss(css, fx) {
      if (!fx || fx === 1) return css;
      return css.replace(/(\d+(?:\.\d+)?)px/g, function (_, n) {
        return scalePx(parseFloat(n), fx) + 'px';
      });
    }
    function scaleStyle(style, fx) {
      if (!style || !fx || fx === 1) return style;
      return style.replace(/(\d+(?:\.\d+)?)px/g, function (_, n) {
        return scalePx(parseFloat(n), fx) + 'px';
      });
    }
    var uiFx = resolveUiScale(API._uiScale || 'auto');
    // persisted speed settings (UI-controlled; override core/param defaults if the user changed them)
    API._speedKey = load('speedKey', API._speedKey || 'Control');
    API._speedUseKey = load('speedUseKey', true);
    API._speedBoost = load('speedBoost', API._speedBoost || 2);
    if (!API._speedUseKey) API.cheats.setSpeed(API._speedBoost);   // "always on" mode applies immediately

    function el(tag, props, kids) {
      var n = document.createElement(tag);
      if (props) for (var k in props) {
        if (k === 'class') n.className = props[k];
        else if (k === 'text') n.textContent = props[k];
        else if (k === 'html') n.innerHTML = props[k];
        else if (k === 'style') n.setAttribute('style', scaleStyle(props[k], uiFx));
        else if (k.slice(0, 2) === 'on' && typeof props[k] === 'function') n.addEventListener(k.slice(2).toLowerCase(), props[k]);
        else if (props[k] != null) n.setAttribute(k, props[k]);
      }
      if (kids) (Array.isArray(kids) ? kids : [kids]).forEach(function (c) { if (c != null) n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
      return n;
    }

    var CSS = "\
:host{position:fixed!important;top:0!important;left:0!important;width:0!important;height:0!important;z-index:2147483647!important;margin:0!important;padding:0!important;border:0!important;pointer-events:none!important;contain:none}\
*{box-sizing:border-box;font-family:var(--font-ui);-webkit-user-select:none;user-select:none}\
#forge-root{--font-ui:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;--font-mono:ui-monospace,'Cascadia Code',Consolas,monospace;\
--fg-bg:#15171c;--fg-bg-elev:#1c1f27;--fg-bg-input:#21242d;--fg-bg-row-alt:#181b22;--fg-border:#2b2f3a;--fg-border-strong:#3a3f4d;\
--fg-text:#e6e9ef;--fg-text-dim:#9aa1b1;--fg-text-faint:#646b7d;--fg-accent:#5b8cff;--fg-accent-weak:#2a3a63;--fg-success:#3ecf8e;--fg-warn:#f0b132;--fg-danger:#f0556a;--fg-frozen:#8b5cf6;\
--sp-1:4px;--sp-2:8px;--sp-3:12px;--sp-4:16px;--sp-5:24px;--rad-sm:4px;--rad-md:7px;--rad-lg:11px;--rad-pill:999px;\
--sh-panel:0 18px 50px rgba(0,0,0,.5),0 0 0 1px var(--fg-border);--row-h:30px;--rail-w:64px;--ease:cubic-bezier(.2,.7,.3,1);--dur:120ms;\
--fs-xs:11px;--fs-sm:12px;--fs-md:13px;--fs-lg:15px;color:var(--fg-text);font-size:var(--fs-md)}\
#forge-root[data-theme=light]{--fg-bg:#f6f7f9;--fg-bg-elev:#fff;--fg-bg-input:#eef0f4;--fg-bg-row-alt:#f0f2f5;--fg-border:#dde0e7;--fg-border-strong:#c7ccd8;--fg-text:#1a1d24;--fg-text-dim:#5a6172;--fg-text-faint:#9097a6;--fg-accent-weak:#dce6ff}\
.fg-panel{position:fixed;display:flex;flex-direction:column;background:var(--fg-bg);border-radius:var(--rad-lg);box-shadow:var(--sh-panel);overflow:hidden;z-index:2147483000;min-width:480px;min-height:360px;pointer-events:auto}\
.fg-titlebar{display:flex;align-items:center;gap:var(--sp-2);height:38px;padding:0 var(--sp-2) 0 var(--sp-3);background:var(--fg-bg-elev);border-bottom:1px solid var(--fg-border);cursor:move;flex:0 0 auto}\
.fg-brand{font-weight:700;font-size:var(--fs-md);letter-spacing:.3px;color:var(--fg-text)}\
.fg-brand b{color:var(--fg-accent)}\
.fg-search{flex:1;height:26px;background:var(--fg-bg-input);border:1px solid var(--fg-border);border-radius:var(--rad-md);color:var(--fg-text);padding:0 var(--sp-3);font-size:var(--fs-sm);outline:none;min-width:80px}\
.fg-search:focus{border-color:var(--fg-accent)}\
.fg-iconbtn{display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;border-radius:var(--rad-md);background:transparent;color:var(--fg-text-dim);border:0;cursor:pointer;font-size:14px;transition:background var(--dur)}\
.fg-iconbtn:hover{background:var(--fg-bg-input);color:var(--fg-text)}\
.fg-body{flex:1;display:flex;min-height:0}\
.fg-rail{flex:0 0 var(--rail-w);display:flex;flex-direction:column;gap:2px;padding:var(--sp-2) var(--sp-1);background:var(--fg-bg-elev);border-right:1px solid var(--fg-border);overflow-y:auto}\
.fg-rail__item{display:flex;flex-direction:column;align-items:center;gap:2px;padding:var(--sp-2) 0;border-radius:var(--rad-md);cursor:pointer;color:var(--fg-text-dim);font-size:10px;transition:all var(--dur);border:0;background:transparent}\
.fg-rail__item .ic{font-size:17px;line-height:1}\
.fg-rail__item:hover{background:var(--fg-bg-input);color:var(--fg-text)}\
.fg-rail__item.is-active{background:var(--fg-accent-weak);color:var(--fg-accent)}\
.fg-content{flex:1;display:flex;flex-direction:column;min-width:0}\
.fg-section-head{display:flex;align-items:center;gap:var(--sp-2);padding:var(--sp-3) var(--sp-4) var(--sp-2);flex:0 0 auto}\
.fg-section-head h2{margin:0;font-size:var(--fs-lg);font-weight:600}\
.fg-count{font-size:var(--fs-xs);color:var(--fg-text-faint);background:var(--fg-bg-input);padding:2px 7px;border-radius:var(--rad-pill)}\
.fg-spacer{flex:1}\
.fg-subtoolbar{display:flex;align-items:center;gap:var(--sp-2);padding:0 var(--sp-4) var(--sp-2);flex-wrap:wrap}\
.fg-segmented{display:inline-flex;background:var(--fg-bg-input);border-radius:var(--rad-md);padding:2px}\
.fg-segmented button{border:0;background:transparent;color:var(--fg-text-dim);padding:3px 12px;border-radius:5px;cursor:pointer;font-size:var(--fs-sm)}\
.fg-segmented button.is-active{background:var(--fg-accent);color:#fff}\
.fg-btn{border:1px solid var(--fg-border-strong);background:var(--fg-bg-input);color:var(--fg-text);padding:4px 11px;border-radius:var(--rad-md);cursor:pointer;font-size:var(--fs-sm);transition:all var(--dur)}\
.fg-btn:hover{border-color:var(--fg-accent);color:var(--fg-accent)}\
.fg-btn--ghost{background:transparent;border-color:transparent;color:var(--fg-text-dim)}\
.fg-btn--danger:hover{border-color:var(--fg-danger);color:var(--fg-danger)}\
.fg-list{flex:1;overflow-y:auto;overflow-x:hidden;position:relative;border-top:1px solid var(--fg-border)}\
.fg-list__sizer{position:relative;width:100%}\
.fg-list__window{position:absolute;top:0;left:0;right:0}\
.fg-row{display:flex;align-items:center;gap:var(--sp-2);height:var(--row-h);padding:0 var(--sp-4);border-bottom:1px solid var(--fg-border);font-size:var(--fs-sm)}\
.fg-row:nth-child(even){background:var(--fg-bg-row-alt)}\
.fg-row.is-frozen{box-shadow:inset 3px 0 0 var(--fg-frozen)}\
.fg-row.is-selected{background:var(--fg-accent-weak)!important;box-shadow:inset 2px 0 0 var(--fg-accent)}\
.fg-cell--id{flex:0 0 52px;color:var(--fg-text-faint);font-family:var(--font-mono);font-size:var(--fs-xs)}\
.fg-cell--name{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}\
.fg-cell--name .dot{display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--fg-accent);margin-right:6px;vertical-align:middle}\
.fg-cell--val{flex:0 0 auto;display:flex;align-items:center;gap:4px}\
.fg-stepper{display:inline-flex;align-items:center;gap:3px}\
.fg-step{min-width:30px;width:auto;padding:0 5px;height:22px;white-space:nowrap;border:1px solid var(--fg-border-strong);background:var(--fg-bg-input);color:var(--fg-text-dim);border-radius:5px;cursor:pointer;font-size:var(--fs-xs);font-family:var(--font-mono)}\
.fg-step:hover{color:var(--fg-accent);border-color:var(--fg-accent)}\
.fg-num{width:68px;height:22px;background:var(--fg-bg-input);border:1px solid var(--fg-border);border-radius:5px;color:var(--fg-text);text-align:right;padding:0 6px;font-family:var(--font-mono);font-size:var(--fs-sm);outline:none}\
.fg-num:focus{border-color:var(--fg-accent)}\
.fg-toggle{width:38px;height:21px;border-radius:var(--rad-pill);background:var(--fg-border-strong);position:relative;cursor:pointer;transition:background var(--dur);border:0;flex:0 0 auto}\
.fg-toggle::after{content:'';position:absolute;top:2px;left:2px;width:17px;height:17px;border-radius:50%;background:#fff;transition:transform var(--dur)}\
.fg-toggle.is-on{background:var(--fg-success)}\
.fg-toggle.is-on::after{transform:translateX(17px)}\
.fg-lock{width:24px;height:24px;border:0;background:transparent;color:var(--fg-text-faint);cursor:pointer;border-radius:5px;font-size:13px;flex:0 0 auto}\
.fg-lock:hover{color:var(--fg-frozen);background:var(--fg-bg-input)}\
.fg-lock.is-frozen{color:var(--fg-frozen)}\
.fg-statusbar{display:flex;align-items:center;gap:var(--sp-2);height:24px;padding:0 var(--sp-3);background:var(--fg-bg-elev);border-top:1px solid var(--fg-border);font-size:var(--fs-xs);color:var(--fg-text-faint);flex:0 0 auto}\
.fg-detail{padding:var(--sp-3) var(--sp-4);overflow-y:auto;flex:1}\
.fg-field{display:flex;align-items:center;gap:var(--sp-2);padding:5px 0;border-bottom:1px solid var(--fg-border);min-width:0}\n.fg-field .fg-stepper{margin-left:auto;flex:0 0 auto}\
.fg-field label{flex:0 0 96px;color:var(--fg-text-dim);font-size:var(--fs-sm)}\
.fg-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:var(--sp-2) var(--sp-4)}\
.fg-toasts{position:fixed;bottom:16px;left:50%;transform:translateX(-50%);display:flex;flex-direction:column;gap:6px;z-index:2147483100;pointer-events:none}\
.fg-toast{background:var(--fg-bg-elev);border:1px solid var(--fg-border);border-left:3px solid var(--fg-accent);color:var(--fg-text);padding:8px 14px;border-radius:var(--rad-md);font-size:var(--fs-sm);box-shadow:var(--sh-panel);animation:fgin var(--dur) var(--ease)}\
.fg-toast.warn{border-left-color:var(--fg-warn)}.fg-toast.danger{border-left-color:var(--fg-danger)}.fg-toast.ok{border-left-color:var(--fg-success)}\
@keyframes fgin{from{opacity:0;transform:translateY(6px)}to{opacity:1}}\
.fg-launcher{position:fixed;pointer-events:auto;width:42px;height:42px;border-radius:50%;background:var(--fg-accent);color:#fff;border:0;cursor:pointer;font-size:18px;z-index:2147482999;box-shadow:var(--sh-panel);display:flex;align-items:center;justify-content:center}\
.fg-launcher:hover{filter:brightness(1.1)}\
.fg-resize{position:absolute;right:0;bottom:0;width:16px;height:16px;cursor:nwse-resize}\
.fg-resize::after{content:'';position:absolute;right:3px;bottom:3px;width:7px;height:7px;border-right:2px solid var(--fg-text-faint);border-bottom:2px solid var(--fg-text-faint)}\
.fg-empty{padding:var(--sp-5);text-align:center;color:var(--fg-text-faint);font-size:var(--fs-sm)}\
.fg-confirm{position:fixed;pointer-events:auto;inset:0;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,.45);z-index:2147483200}\
.fg-confirm__box{background:var(--fg-bg-elev);border:1px solid var(--fg-border);border-radius:var(--rad-lg);padding:var(--sp-4);max-width:340px;box-shadow:var(--sh-panel)}\
.fg-confirm__box p{margin:0 0 var(--sp-4)}.fg-confirm__row{display:flex;justify-content:flex-end;gap:var(--sp-2)}\
input::placeholder{color:var(--fg-text-faint)}\
.fg-list::-webkit-scrollbar,.fg-rail::-webkit-scrollbar,.fg-detail::-webkit-scrollbar{width:9px}\
.fg-list::-webkit-scrollbar-thumb,.fg-detail::-webkit-scrollbar-thumb{background:var(--fg-border-strong);border-radius:5px}";

    // ---------- shadow host ----------
    var host = el('div', { id: 'forge-host' });
    host.style.cssText = 'position:fixed!important;top:0!important;left:0!important;width:0!important;height:0!important;z-index:2147483647!important;margin:0!important;padding:0!important;border:0!important;pointer-events:none!important;overflow:visible!important';
    document.body.appendChild(host);
    var shadow = host.attachShadow({ mode: 'open' });
    var rootEl = el('div', { id: 'forge-root' });
    rootEl.setAttribute('data-theme', load('theme', 'dark'));
    shadow.appendChild(el('style', { text: scalePxCss(CSS, uiFx) }));
    shadow.appendChild(rootEl);

    // Swallow events so panel interaction never leaks to the game. BUBBLE phase: the panel's own
    // inputs receive the event first (target phase), then we stop it before it reaches document
    // (where RPG Maker's Input/TouchInput listen). Capture phase would block the inputs themselves.
    ['keydown', 'keyup', 'keypress', 'wheel', 'mousedown', 'mouseup', 'mousemove', 'click', 'dblclick',
     'pointerdown', 'pointerup', 'pointermove', 'pointercancel', 'touchstart', 'touchend', 'touchmove', 'touchcancel', 'contextmenu'].forEach(function (t) {
      rootEl.addEventListener(t, function (e) { e.stopPropagation(); }, false);
    });
    function isEditable(el) { return el && (el.tagName === 'INPUT' || el.tagName === 'SELECT' || el.tagName === 'TEXTAREA'); }
    rootEl.addEventListener('focusin', function (e) { if (isEditable(e.target)) API.CHEAT.uiFocused = true; }, true);
    rootEl.addEventListener('focusout', function () { setTimeout(function () { API.CHEAT.uiFocused = !!(shadow.activeElement && isEditable(shadow.activeElement)); }, 0); }, true);
    window.addEventListener('blur', function () { API.CHEAT.uiFocused = false; });   // never latch the game-input gate
    // Backup engine-level gate: while a panel input is focused, drop the game's keyboard handler.
    if (typeof Input !== 'undefined' && Input._onKeyDown) { var _okd = Input._onKeyDown; Input._onKeyDown = function (e) { if (API.CHEAT.uiFocused) return; _okd.call(this, e); }; }
    if (typeof Input !== 'undefined' && Input._onKeyUp) { var _oku = Input._onKeyUp; Input._onKeyUp = function (e) { if (API.CHEAT.uiFocused) return; _oku.call(this, e); }; }

    // ---------- toasts ----------
    var toasts = el('div', { class: 'fg-toasts' }); rootEl.appendChild(toasts);
    function toast(msg, kind) { var t = el('div', { class: 'fg-toast ' + (kind || ''), text: msg }); toasts.appendChild(t); setTimeout(function () { t.remove(); }, 2200); }
    function confirmBox(msg, onYes) {
      var box = el('div', { class: 'fg-confirm' }, el('div', { class: 'fg-confirm__box' }, [
        el('p', { text: msg }),
        el('div', { class: 'fg-confirm__row' }, [
          el('button', { class: 'fg-btn fg-btn--ghost', text: 'Cancel', onclick: function () { box.remove(); } }),
          el('button', { class: 'fg-btn fg-btn--danger', text: 'Confirm', onclick: function () { box.remove(); onYes(); } })
        ])
      ]));
      rootEl.appendChild(box);
    }

    // ---------- panel skeleton ----------
    var vw = window.innerWidth || 816, vh = window.innerHeight || 624;
    // Default size fits the window (many MV games are ~816x624); leave a margin.
    var st = load('panel', { x: scalePx(16, uiFx), y: scalePx(16, uiFx), w: Math.min(scalePx(880, uiFx), vw - scalePx(32, uiFx)), h: Math.min(scalePx(560, uiFx), vh - scalePx(32, uiFx)) });
    st.w = Math.max(scalePx(420, uiFx), Math.min(st.w, vw - scalePx(8, uiFx))); st.h = Math.max(scalePx(320, uiFx), Math.min(st.h, vh - scalePx(8, uiFx)));
    st.x = Math.max(0, Math.min(st.x, vw - st.w)); st.y = Math.max(0, Math.min(st.y, vh - st.h));   // keep fully on-screen
    var panel = el('div', { class: 'fg-panel' });
    panel.style.left = st.x + 'px'; panel.style.top = st.y + 'px'; panel.style.width = st.w + 'px'; panel.style.height = st.h + 'px';
    var search = el('input', { class: 'fg-search', type: 'text', placeholder: 'Search…  (Ctrl+K)' });
    var titlebar = el('div', { class: 'fg-titlebar' }, [
      el('span', { class: 'fg-brand', html: '<b>F</b>orge' }),
      search,
      el('button', { class: 'fg-iconbtn', title: 'Rescan', text: '⟳', onclick: function () { render(); toast('Rescanned'); } }),
      el('button', { class: 'fg-iconbtn', title: 'Theme', text: '◑', onclick: function () { var t = rootEl.getAttribute('data-theme') === 'light' ? 'dark' : 'light'; rootEl.setAttribute('data-theme', t); store('theme', t); } }),
      el('button', { class: 'fg-iconbtn', title: 'Close (F10)', text: '✕', onclick: function () { hide(); } })
    ]);
    var rail = el('div', { class: 'fg-rail' });
    var content = el('div', { class: 'fg-content' });
    var statusbar = el('div', { class: 'fg-statusbar' });
    panel.appendChild(titlebar);
    panel.appendChild(el('div', { class: 'fg-body' }, [rail, content]));
    panel.appendChild(statusbar);
    var resize = el('div', { class: 'fg-resize' }); panel.appendChild(resize);
    rootEl.appendChild(panel);

    // ---------- launcher (docks to bottom-right corner by default; 'launcherPos' is a fresh key so
    // any stale mid-screen position from older builds is ignored) ----------
    var lp = load('launcherPos', { x: vw - scalePx(56, uiFx), y: vh - scalePx(56, uiFx) });
    lp.x = Math.max(scalePx(4, uiFx), Math.min(lp.x, vw - scalePx(46, uiFx))); lp.y = Math.max(scalePx(4, uiFx), Math.min(lp.y, vh - scalePx(46, uiFx)));
    var launcher = el('button', { class: 'fg-launcher', text: '⚒', title: 'Forge (F10)' });
    launcher.style.left = lp.x + 'px'; launcher.style.top = lp.y + 'px';
    launcher.addEventListener('click', function (e) { if (!launcher._dragged) toggle(); });
    rootEl.appendChild(launcher);
    makeDraggable(launcher, launcher, function (x, y) { store('launcherPos', { x: x, y: y }); }, true);

    // ---------- drag / resize ----------
    function makeDraggable(handle, target, onEnd, isLauncher) {
      handle.addEventListener('mousedown', function (e) {
        if (e.target.closest && e.target.closest('input,button.fg-iconbtn')) return;
        e.preventDefault(); e.stopPropagation(); var sx = e.clientX, sy = e.clientY, ox = parseInt(target.style.left) || 0, oy = parseInt(target.style.top) || 0, moved = false;
        if (isLauncher) target._dragged = false;
        function mv(ev) { ev.stopPropagation(); var dx = ev.clientX - sx, dy = ev.clientY - sy; if (Math.abs(dx) + Math.abs(dy) > 3) moved = true; var nx = Math.max(0, Math.min(window.innerWidth - target.offsetWidth, ox + dx)), ny = Math.max(0, Math.min(window.innerHeight - scalePx(30, uiFx), oy + dy)); target.style.left = nx + 'px'; target.style.top = ny + 'px'; if (isLauncher) target._dragged = moved; }
        function up(ev) { if (ev) { ev.stopPropagation(); ev.preventDefault(); } document.removeEventListener('mousemove', mv, true); document.removeEventListener('mouseup', up, true); if (onEnd) onEnd(parseInt(target.style.left), parseInt(target.style.top)); setTimeout(function () { if (isLauncher) target._dragged = false; }, 0); }
        document.addEventListener('mousemove', mv, true); document.addEventListener('mouseup', up, true);
      });
    }
    makeDraggable(titlebar, panel, function (x, y) { st.x = x; st.y = y; store('panel', st); });
    resize.addEventListener('mousedown', function (e) {
      e.preventDefault(); e.stopPropagation(); var sx = e.clientX, sy = e.clientY, ow = panel.offsetWidth, oh = panel.offsetHeight;
      function mv(ev) { ev.stopPropagation(); var w = Math.max(scalePx(480, uiFx), ow + ev.clientX - sx), h = Math.max(scalePx(360, uiFx), oh + ev.clientY - sy); panel.style.width = w + 'px'; panel.style.height = h + 'px'; if (activeRenderer && activeRenderer.onResize) activeRenderer.onResize(); }
      function up(ev) { if (ev) { ev.stopPropagation(); ev.preventDefault(); } document.removeEventListener('mousemove', mv, true); document.removeEventListener('mouseup', up, true); st.w = panel.offsetWidth; st.h = panel.offsetHeight; store('panel', st); }
      document.addEventListener('mousemove', mv, true); document.addEventListener('mouseup', up, true);
    });

    // ---------- reusable virtualized list ----------
    function VirtualList(opts) {
      // opts: rowH, getModel()->[], renderRow(rowEl, item), matches(item, query)
      var listEl = el('div', { class: 'fg-list' });
      var sizer = el('div', { class: 'fg-list__sizer' });
      var win = el('div', { class: 'fg-list__window' });
      sizer.appendChild(win); listEl.appendChild(sizer);
      var rowH = opts.rowH || scalePx(30, uiFx), pool = [], model = [], view = [], query = '';
      // ONE delegated row click (recycled rows must not accumulate per-draw listeners).
      if (opts.onRowClick) listEl.addEventListener('click', function (e) { var r = e.target && e.target.closest ? e.target.closest('.fg-row') : null; if (r && r._item) opts.onRowClick(r._item); });
      function rebuild() { model = opts.getModel() || []; applyFilter(); }
      function applyFilter() {
        view = query ? model.filter(function (it) { return opts.matches(it, query); }) : model;
        sizer.style.height = (view.length * rowH) + 'px';
        var em = listEl.querySelector('.fg-empty');
        if (!view.length) { pool.forEach(function (r) { r.style.display = 'none'; }); if (!em) listEl.appendChild(el('div', { class: 'fg-empty', text: 'Nothing here' })); }
        else if (em) em.remove();
        lastFirst = -1; draw(true);     // content changed -> force re-render
      }
      var lastFirst = -1;
      function draw(force) {
        var scroll = listEl.scrollTop, h = listEl.clientHeight || 400;
        var first = Math.max(0, Math.floor(scroll / rowH) - 4);
        if (!force && first === lastFirst) return;          // window unchanged during scroll -> skip re-render
        lastFirst = first;
        var count = Math.ceil(h / rowH) + 8;
        var last = Math.min(view.length, first + count);
        win.style.transform = 'translateY(' + (first * rowH) + 'px)';
        var need = last - first;
        while (pool.length < need) { var r = el('div', { class: 'fg-row' }); win.appendChild(r); pool.push(r); }
        for (var i = 0; i < pool.length; i++) {
          var r = pool[i];
          if (i < need) { r.style.display = 'flex'; r._item = view[first + i]; opts.renderRow(r, view[first + i]); } else { r.style.display = 'none'; r._item = null; }
        }
      }
      var raf = null;
      listEl.addEventListener('scroll', function () { if (raf) return; raf = requestAnimationFrame(function () { raf = null; draw(false); }); });
      return { el: listEl, rebuild: rebuild, applyFilter: applyFilter, draw: function () { draw(true); }, setQuery: function (q) { query = q; applyFilter(); }, onResize: function () { draw(true); },
        refresh: function () { draw(true); } };
    }

    // numeric stepper control
    function stepper(getVal, setVal, opts) {
      opts = opts || {};
      var wrap = el('div', { class: 'fg-stepper' });
      var input = el('input', { class: 'fg-num', type: 'text' });
      function sync() { input.value = getVal(); }
      function commit(v) { setVal(v); sync(); if (opts.after) opts.after(); }
      [['−100', -100], ['−1', -1]].forEach(function (s) { wrap.appendChild(el('button', { class: 'fg-step', text: s[0], onclick: function (e) { commit(getVal() + s[1] * (e.shiftKey ? 10 : 1)); } })); });
      wrap.appendChild(input);
      [['+1', 1], ['+100', 100]].forEach(function (s) { wrap.appendChild(el('button', { class: 'fg-step', text: s[0], onclick: function (e) { commit(getVal() + s[1] * (e.shiftKey ? 10 : 1)); } })); });
      input.addEventListener('keydown', function (e) { if (e.key === 'Enter') { commit(parse(input.value)); input.blur(); } else if (e.key === 'Escape') { sync(); input.blur(); } });
      input.addEventListener('blur', function () { commit(parse(input.value)); });
      function parse(s) { var n = Number(String(s).replace(/[^0-9.\-]/g, '')); return isNaN(n) ? getVal() : n; }
      sync();
      return { el: wrap, sync: sync };
    }

    // ---------- sections ----------
    var activeRenderer = null, currentSection = null;
    var SECTIONS = [];
    function section(id, icon, title, builder) { SECTIONS.push({ id: id, icon: icon, title: title, builder: builder }); }

    function listSection(getModel, renderRow, matches, headExtra) {
      return function (body, head) {
        if (headExtra) headExtra(head);
        var vl = VirtualList({ getModel: getModel, renderRow: renderRow, matches: matches || defaultMatch });
        body.appendChild(vl.el);
        vl.rebuild();
        return { vl: vl, onResize: vl.onResize, refresh: function () { vl.rebuild(); }, setQuery: vl.setQuery, count: function () { return (getModel() || []).length; } };
      };
    }
    function defaultMatch(it, q) { q = q.toLowerCase(); return String(it.id) === q || (it.name && it.name.toLowerCase().indexOf(q) >= 0); }

    // Variables
    section('vars', '▣', 'Variables', listSection(
      function () { return API.ops.vars.list(); },
      function (row, it) {
        row.className = 'fg-row' + (API.locks.isVarFrozen(it.id) ? ' is-frozen' : '');
        row.innerHTML = '';
        row.appendChild(el('span', { class: 'fg-cell--id', text: it.id }));
        row.appendChild(el('span', { class: 'fg-cell--name', text: it.name, title: it.name }));
        var val = el('span', { class: 'fg-cell--val' });
        var sp = stepper(function () { return API.ops.vars.get(it.id); }, function (v) { API.ops.vars.set(it.id, v); if (API.locks.isVarFrozen(it.id)) API.locks.freezeVar(it.id, true); }, {});
        val.appendChild(sp.el); row.appendChild(val);
        row.appendChild(lockBtn(API.locks.isVarFrozen(it.id), function (on) { API.locks.freezeVar(it.id, on); refreshActive(); }));
      }
    ));

    // Switches
    section('switches', '⇄', 'Switches', listSection(
      function () { return API.ops.switches.list(); },
      function (row, it) {
        row.className = 'fg-row' + (API.locks.isSwitchFrozen(it.id) ? ' is-frozen' : '');
        row.innerHTML = '';
        row.appendChild(el('span', { class: 'fg-cell--id', text: it.id }));
        row.appendChild(el('span', { class: 'fg-cell--name', text: it.name, title: it.name }));
        var val = el('span', { class: 'fg-cell--val' });
        var tg = el('button', { class: 'fg-toggle' + (API.ops.switches.get(it.id) ? ' is-on' : '') });
        tg.addEventListener('click', function () { API.ops.switches.set(it.id, !API.ops.switches.get(it.id)); if (API.locks.isSwitchFrozen(it.id)) API.locks.freezeSwitch(it.id, true); tg.classList.toggle('is-on', API.ops.switches.get(it.id)); });
        val.appendChild(tg); row.appendChild(val);
        row.appendChild(lockBtn(API.locks.isSwitchFrozen(it.id), function (on) { API.locks.freezeSwitch(it.id, on); refreshActive(); }));
      }
    ));

    // Items / Weapons / Armors (segmented)
    section('inv', '🜚', 'Items', function (body, head) {
      var kind = 'item';
      var seg = el('div', { class: 'fg-segmented' });
      ['item', 'weapon', 'armor'].forEach(function (k) {
        var b = el('button', { class: k === kind ? 'is-active' : '', text: k.charAt(0).toUpperCase() + k.slice(1) + 's' });
        b.addEventListener('click', function () { kind = k; seg.querySelectorAll('button').forEach(function (x) { x.classList.remove('is-active'); }); b.classList.add('is-active'); vl.rebuild(); });
        seg.appendChild(b);
      });
      head.appendChild(seg);
      var vl = VirtualList({
        getModel: function () { return API.ops.inv.list(kind); },
        matches: defaultMatch,
        renderRow: function (row, it) {
          row.className = 'fg-row' + (API.locks.isItemFrozen(kind, it.id) ? ' is-frozen' : '');
          row.innerHTML = '';
          row.appendChild(el('span', { class: 'fg-cell--id', text: it.id }));
          row.appendChild(el('span', { class: 'fg-cell--name', text: it.name, title: it.description || it.name }));
          var val = el('span', { class: 'fg-cell--val' });
          var sp = stepper(function () { return API.ops.inv.count(kind, it.id); }, function (v) { API.ops.inv.setCount(kind, it.id, v); }, {});
          val.appendChild(sp.el);
          val.appendChild(el('button', { class: 'fg-step', text: 'Max', style: 'width:auto;padding:0 6px', onclick: function () { API.ops.inv.max(kind, it.id); sp.sync(); } }));
          row.appendChild(val);
          row.appendChild(lockBtn(API.locks.isItemFrozen(kind, it.id), function (on) { API.locks.freezeItem(kind, it.id, on); refreshActive(); }));
        }
      });
      body.appendChild(vl.el); vl.rebuild();
      return { onResize: vl.onResize, refresh: function () { vl.rebuild(); }, setQuery: vl.setQuery, count: function () { return API.ops.inv.list(kind).length; } };
    });

    // Actors (master-detail)
    section('actors', '👤', 'Actors', function (body) {
      var detail = el('div', { class: 'fg-detail' });
      var selectedId = null;
      var vl = VirtualList({
        rowH: 30, matches: defaultMatch,
        getModel: function () { return API.ops.actors.list(); },
        onRowClick: function (it) { showActor(it.id); },
        renderRow: function (row, it) {
          row.className = 'fg-row' + (it.id === selectedId ? ' is-selected' : '');
          row.style.cursor = 'pointer';
          row.innerHTML = '';
          row.appendChild(el('span', { class: 'fg-cell--id', text: it.id }));
          row.appendChild(el('span', { class: 'fg-cell--name', html: (it.inParty ? '<span class="dot"></span>' : '') + escapeHtml(it.name) }));
          row.appendChild(el('span', { class: 'fg-cell--val', text: 'Lv ' + it.level }));
        }
      });
      var split = el('div', { style: 'flex:1;display:flex;min-height:0' });
      var left = el('div', { style: 'flex:0 0 240px;display:flex;flex-direction:column;border-right:1px solid var(--fg-border)' });
      left.appendChild(vl.el);
      split.appendChild(left); split.appendChild(detail);
      body.appendChild(split); vl.rebuild();
      var firstA = API.ops.actors.list()[0];           // auto-select first actor so detail isn't empty
      if (firstA) showActor(firstA.id);
      function showActor(id) {
        selectedId = id; vl.draw();                    // re-highlight the selected row in the (virtualized) list
        var a = API.ops.actors.get(id); detail.innerHTML = '';
        if (!a) { detail.appendChild(el('div', { class: 'fg-empty', text: 'Actor not initialized (start a game first)' })); return; }
        detail.appendChild(el('h2', { text: a.name + '  ·  Lv ' + a.level, style: 'margin:0 0 12px;font-size:15px' }));
        var grid = el('div', { class: 'fg-grid' });
        grid.appendChild(numField('Level', function () { return API.ops.actors.get(id).level; }, function (v) { API.ops.actors.setLevel(id, v); showActor(id); }));
        grid.appendChild(numField('EXP', function () { return API.ops.actors.get(id).exp; }, function (v) { API.ops.actors.setExp(id, v); showActor(id); }));
        grid.appendChild(statField('HP', id, 'hp', function () { return API.ops.actors.get(id).hp; }, function () { return API.ops.actors.get(id).mhp; }, API.ops.actors.setHp));
        grid.appendChild(statField('MP', id, 'mp', function () { return API.ops.actors.get(id).mp; }, function () { return API.ops.actors.get(id).mmp; }, API.ops.actors.setMp));
        grid.appendChild(statField('TP', id, 'tp', function () { return API.ops.actors.get(id).tp; }, function () { return 100; }, API.ops.actors.setTp));
        a.params.forEach(function (p) { grid.appendChild(numField(p.name, function () { return API.ops.actors.get(id).params[p.id].value; }, function (v) { API.ops.actors.setParam(id, p.id, v); })); });
        detail.appendChild(grid);
        var actbar = el('div', { style: 'display:flex;gap:8px;margin:14px 0' }, [
          el('button', { class: 'fg-btn', text: 'Recover All', onclick: function () { API.ops.actors.recover(id); showActor(id); } }),
          el('button', { class: 'fg-btn', text: a.inParty ? 'Remove from Party' : 'Add to Party', onclick: function () { if (a.inParty) API.ops.actors.removeFromParty(id); else API.ops.actors.addToParty(id); vl.rebuild(); showActor(id); } })
        ]);
        detail.appendChild(actbar);
        // skills
        detail.appendChild(el('h2', { text: 'Skills', style: 'font-size:13px;margin:10px 0 4px;color:var(--fg-text-dim)' }));
        var skbox = el('div', { style: 'max-height:140px;overflow:auto;border:1px solid var(--fg-border);border-radius:7px' });
        a.skills.forEach(function (s) {
          var r = el('div', { class: 'fg-field', style: 'padding:3px 10px' }, [
            el('span', { style: 'flex:1;font-size:12px', text: s.id + ': ' + s.name }),
            el('button', { class: 'fg-btn fg-btn--ghost', text: s.learned ? 'Forget' : 'Learn', onclick: function () { if (s.learned) API.ops.actors.forget(id, s.id); else API.ops.actors.learn(id, s.id); showActor(id); } })
          ]);
          skbox.appendChild(r);
        });
        detail.appendChild(skbox);
      }
      function numField(label, get, set) {
        var f = el('div', { class: 'fg-field' }); f.appendChild(el('label', { text: label }));
        f.appendChild(stepper(get, set, {}).el);
        f.appendChild(el('span', { style: 'flex:0 0 24px;width:24px' }));   // empty lock slot -> steppers align with HP/MP/TP rows
        return f;
      }
      function statField(label, id, stat, get, getMax, setFn) {
        var f = el('div', { class: 'fg-field' }); f.appendChild(el('label', { text: label }));
        f.appendChild(stepper(get, function (v) { setFn(id, v); if (API.locks.isStatFrozen(id, stat)) API.locks.freezeStat(id, stat, true); }, {}).el);
        f.appendChild(lockBtn(API.locks.isStatFrozen(id, stat), function (on) { API.locks.freezeStat(id, stat, on); }));
        return f;
      }
      return { onResize: vl.onResize, refresh: function () { vl.rebuild(); }, setQuery: vl.setQuery, count: function () { return API.ops.actors.list().length; } };
    });

    // Party / Main
    section('party', '★', 'Party', function (body) {
      var d = el('div', { class: 'fg-detail' });
      function rebuild() {
        d.innerHTML = '';
        d.appendChild(el('div', { class: 'fg-field' }, [
          el('label', { text: 'Gold' }),
          stepper(function () { return API.ops.gold.get(); }, function (v) { API.ops.gold.set(v); }, {}).el,
          lockBtn(API.LOCK.gold != null, function (on) { API.locks.freezeGold(on); rebuild(); })
        ]));
        d.appendChild(el('div', { class: 'fg-field' }, [el('label', { text: 'Steps' }), el('span', { text: API.ops.party.steps() })]));
        d.appendChild(el('div', { class: 'fg-field' }, [el('label', { text: 'Members' }), el('span', { text: API.ops.party.members().map(function (m) { return m.name; }).join(', ') || '(none)' })]));
        d.appendChild(el('h2', { text: 'Quick actions', style: 'font-size:13px;margin:14px 0 6px;color:var(--fg-text-dim)' }));
        d.appendChild(el('div', { style: 'display:flex;gap:8px;flex-wrap:wrap' }, [
          el('button', { class: 'fg-btn', text: 'Gold = Max', onclick: function () { API.ops.gold.set(API.ops.gold.max()); rebuild(); toast('Gold maxed', 'ok'); } }),
          el('button', { class: 'fg-btn', text: 'Heal Party', onclick: function () { API.ops.party.members().forEach(function (m) { API.ops.actors.recover(m.id); }); toast('Party healed', 'ok'); } })
        ]));
      }
      body.appendChild(d); rebuild();
      return { refresh: rebuild, count: function () { return API.ops.party.members().length; } };
    });

    // Map / Teleport
    section('map', '🗺', 'Map', function (body) {
      var d = el('div', { class: 'fg-detail' });
      function rebuild() {
        d.innerHTML = '';
        var cur = API.ops.map.current();
        d.appendChild(el('div', { class: 'fg-field' }, [el('label', { text: 'Current' }), el('span', { text: 'Map ' + cur.mapId + ' @ (' + cur.x + ',' + cur.y + ')' })]));
        var sel = el('select', { class: 'fg-search', style: 'flex:1' });
        API.ops.map.list().forEach(function (m) { sel.appendChild(el('option', { value: m.id, text: m.id + ': ' + m.name })); });
        sel.value = cur.mapId;
        var xIn = el('input', { class: 'fg-num', value: cur.x }), yIn = el('input', { class: 'fg-num', value: cur.y });
        d.appendChild(el('div', { class: 'fg-field' }, [el('label', { text: 'Teleport to' }), sel]));
        d.appendChild(el('div', { class: 'fg-field' }, [el('label', { text: 'X / Y' }), xIn, yIn,
          el('button', { class: 'fg-btn', text: 'Go', onclick: function () { API.ops.map.teleport(Number(sel.value), Number(xIn.value), Number(yIn.value), 0, 2); toast('Teleporting…', 'ok'); } })]));
        d.appendChild(el('div', { class: 'fg-field' }, [el('label', { text: 'Noclip' }),
          (function () { var t = el('button', { class: 'fg-toggle' + (API.ops.map.isNoclip() ? ' is-on' : '') }); t.addEventListener('click', function () { var on = !API.ops.map.isNoclip(); API.ops.map.noclip(on); t.classList.toggle('is-on', on); }); return t; })()]));
        d.appendChild(el('div', { class: 'fg-field' }, [el('label', { text: 'Move speed' }),
          stepper(function () { return (window.$gamePlayer && $gamePlayer._moveSpeed) || 4; }, function (v) { API.ops.map.speed(v); }, {}).el]));
      }
      body.appendChild(d); rebuild();
      return { refresh: rebuild, count: function () { return API.ops.map.list().length; } };
    });

    // Common Events
    section('commonev', '⚡', 'Common Ev.', listSection(
      function () { return API.ops.commonev.list(); },
      function (row, it) {
        row.className = 'fg-row'; row.innerHTML = '';
        row.appendChild(el('span', { class: 'fg-cell--id', text: it.id }));
        row.appendChild(el('span', { class: 'fg-cell--name', text: it.name, title: it.name }));
        row.appendChild(el('span', { class: 'fg-cell--val' }, el('button', { class: 'fg-btn', text: 'Run', onclick: function () { confirmBox('Run common event ' + it.id + ' (' + it.name + ')?', function () { API.ops.commonev.run(it.id); toast('Reserved CE ' + it.id, 'ok'); }); } })));
      }
    ));

    // Data Lock (aggregated frozen targets)
    section('locks', '🛡', 'Data Lock', function (body, head) {
      head.appendChild(el('button', { class: 'fg-btn fg-btn--danger', text: 'Unfreeze all', onclick: function () { API.locks.clearAll(); rebuild(); toast('All unfrozen'); } }));
      var d = el('div', { class: 'fg-detail' });
      function rebuild() {
        d.innerHTML = '';
        var s = API.locks.summary();
        if (!s.length) { d.appendChild(el('div', { class: 'fg-empty', text: 'No frozen values. Use the lock icon on any row to freeze it.' })); return; }
        s.forEach(function (row) {
          d.appendChild(el('div', { class: 'fg-field' }, [
            el('span', { style: 'flex:1;font-size:12px', text: row.label }),
            el('span', { style: 'color:var(--fg-frozen);font-family:var(--font-mono);margin-right:8px', text: String(row.value) }),
            el('button', { class: 'fg-btn fg-btn--ghost', text: 'Unfreeze', onclick: function () { unfreeze(row); rebuild(); } })
          ]));
        });
      }
      function unfreeze(row) {
        if (row.type === 'var') API.locks.freezeVar(row.id, false);
        else if (row.type === 'switch') API.locks.freezeSwitch(row.id, false);
        else if (row.type === 'item') { var p = row.key.split(':'); API.LOCK.items.delete(row.key); }
        else if (row.type === 'stat') { API.LOCK.stats.delete(row.key); }
        else if (row.type === 'gold') API.locks.freezeGold(false);
        else if (row.type === 'noclip') API.ops.map.noclip(false);
      }
      body.appendChild(d); rebuild();
      return { refresh: rebuild, count: function () { return API.locks.summary().length; } };
    });

    // Battle cheats
    section('battle', '⚔', 'Cheats', function (body) {
      var d = el('div', { class: 'fg-detail' });
      function tog(label, get, set) {
        var t = el('button', { class: 'fg-toggle' + (get() ? ' is-on' : '') });
        t.addEventListener('click', function () { var v = !get(); set(v); t.classList.toggle('is-on', v); });
        return el('div', { class: 'fg-field' }, [el('label', { text: label }), t]);
      }
      d.appendChild(tog('God mode (blocks HP loss)', function () { return API.CHEAT.god; }, API.cheats.setGod));
      d.appendChild(tog('One-hit kill', function () { return API.CHEAT.ohko; }, API.cheats.setOhko));
      d.appendChild(tog('No random encounters', function () { return API.CHEAT.noEncounter; }, API.cheats.setNoEncounter));
      // ---- game speed (speedhack) ----
      d.appendChild(el('h2', { text: 'Game speed', style: 'font-size:13px;margin:14px 0 6px;color:var(--fg-text-dim)' }));
      var speedRow = el('div', { class: 'fg-field' });
      speedRow.appendChild(el('label', { text: 'Speed' }));
      var seg = el('div', { class: 'fg-segmented', style: 'flex-wrap:wrap' });
      var presets = [['0.5×', 0.5], ['1×', 1], ['2×', 2], ['3×', 3], ['5×', 5], ['8×', 8]];
      function keyLabel(k) { return k === 'Control' ? 'Ctrl' : (k === ' ' ? 'Space' : k); }
      // In KEY mode the highlight = the ARMED target (_speedBoost); in ALWAYS-ON mode = the live speed.
      function targetSpeed() { return API._speedUseKey ? (API._speedBoost || 2) : (API.CHEAT.speed || 1); }
      function syncSeg() { var t = targetSpeed(); Array.prototype.forEach.call(seg.children, function (b) { b.classList.toggle('is-active', Number(b.dataset.v) === t); }); if (typeof custom !== 'undefined' && custom) custom.value = t; }
      // Picking a speed ARMS the target. It only changes the live game speed if key-mode is OFF, or if
      // the speedhack is already active (then it live-updates). So buttons respect the key toggle.
      function pick(v) {
        API._speedBoost = v; store('speedBoost', v);
        if (!API._speedUseKey || API.CHEAT.speed !== 1) { API.cheats.setSpeed(v); toast('Speed ' + v + '×', 'ok'); }
        else { toast('Armed ' + v + '× — hold ' + keyLabel(API._speedKey) + ' to fast-forward', 'ok'); }
        syncSeg();
      }
      presets.forEach(function (p) {
        var b = el('button', { text: p[0] }); b.dataset.v = p[1];
        b.addEventListener('click', function () { pick(p[1]); });
        seg.appendChild(b);
      });
      speedRow.appendChild(seg);
      d.appendChild(speedRow);
      var customRow = el('div', { class: 'fg-field' });
      customRow.appendChild(el('label', { text: 'Custom ×' }));
      var custom = el('input', { class: 'fg-num', type: 'text', value: targetSpeed() });
      custom.addEventListener('keydown', function (e) { if (e.key === 'Enter') { pick(Number(custom.value) || 1); custom.blur(); } });
      custom.addEventListener('blur', function () { pick(Number(custom.value) || 1); });
      customRow.appendChild(custom);
      d.appendChild(customRow);

      // ---- use-key toggle (off => speed is always on) ----
      var useKeyRow = el('div', { class: 'fg-field' });
      useKeyRow.appendChild(el('label', { text: 'Use hold key' }));
      var ukTog = el('button', { class: 'fg-toggle' + (API._speedUseKey ? ' is-on' : '') });
      ukTog.addEventListener('click', function () {
        speedHeld = false;   // changing mode ends any active hold so a later key-release won't reset speed
        var on = !API._speedUseKey; API._speedUseKey = on; store('speedUseKey', on); ukTog.classList.toggle('is-on', on);
        keyRow.style.display = on ? '' : 'none';
        if (on) { API.cheats.setSpeed(1); toast('Speed: hold ' + keyLabel(API._speedKey) + ' to fast-forward', 'ok'); }
        else { API.cheats.setSpeed(API._speedBoost || 2); toast('Speed: always on at ' + (API._speedBoost || 2) + '×', 'ok'); }
        syncSeg();
      });
      useKeyRow.appendChild(ukTog);
      d.appendChild(useKeyRow);

      // ---- rebindable key ----
      var keyRow = el('div', { class: 'fg-field' });
      keyRow.appendChild(el('label', { text: 'Hold key' }));
      var keyBtn = el('button', { class: 'fg-btn', text: keyLabel(API._speedKey) });
      keyBtn.addEventListener('click', function () {
        keyBtn.textContent = 'Press a key…'; API._capturingSpeedKey = true;
        function cap(ev) {
          ev.preventDefault(); ev.stopPropagation();
          window.removeEventListener('keydown', cap, true); API._capturingSpeedKey = false;
          if (ev.key !== 'Escape') { API._speedKey = ev.key; store('speedKey', ev.key); }
          keyBtn.textContent = keyLabel(API._speedKey);
        }
        window.addEventListener('keydown', cap, true);
      });
      keyRow.appendChild(keyBtn);
      keyRow.style.display = API._speedUseKey ? '' : 'none';
      d.appendChild(keyRow);
      syncSeg();
      d.appendChild(el('h2', { text: 'In-battle actions', style: 'font-size:13px;margin:14px 0 6px;color:var(--fg-text-dim)' }));
      d.appendChild(el('div', { style: 'display:flex;gap:8px;flex-wrap:wrap' }, [
        el('button', { class: 'fg-btn', text: 'Instant Win', onclick: function () { API.cheats.instantWin(); toast(API.ops.battle.inBattle() ? 'Enemies downed' : 'Not in battle', API.ops.battle.inBattle() ? 'ok' : 'warn'); } }),
        el('button', { class: 'fg-btn', text: 'Flee / Abort', onclick: function () { API.cheats.flee(); } })
      ]));
      body.appendChild(d);
      return { refresh: function () {}, count: function () { return 0; } };
    });

    // ---------- render / navigation ----------
    function escapeHtml(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
    function lockBtn(frozen, onToggle) {
      var b = el('button', { class: 'fg-lock' + (frozen ? ' is-frozen' : ''), text: frozen ? '🔒' : '🔓', title: 'Freeze value' });
      b.addEventListener('click', function () { frozen = !frozen; b.className = 'fg-lock' + (frozen ? ' is-frozen' : ''); b.textContent = frozen ? '🔒' : '🔓'; onToggle(frozen); });
      return b;
    }
    function refreshActive() { if (activeRenderer && activeRenderer.refresh) activeRenderer.refresh(); updateStatus(); }

    SECTIONS.forEach(function (s) {
      var item = el('button', { class: 'fg-rail__item', title: s.title }, [el('span', { class: 'ic', text: s.icon }), el('span', { text: s.title.split(' ')[0] })]);
      item.addEventListener('click', function () { selectSection(s.id); });
      s._rail = item; rail.appendChild(item);
    });

    function selectSection(id) {
      currentSection = id;
      SECTIONS.forEach(function (s) { s._rail.classList.toggle('is-active', s.id === id); });
      render();
      store('lastSection', id);
    }
    function render() {
      var s = SECTIONS.filter(function (x) { return x.id === currentSection; })[0]; if (!s) return;
      content.innerHTML = '';
      var head = el('div', { class: 'fg-subtoolbar' });
      var sectionHead = el('div', { class: 'fg-section-head' }, [el('h2', { text: s.title }), el('span', { class: 'fg-count', text: '' }), el('span', { class: 'fg-spacer' })]);
      content.appendChild(sectionHead);
      content.appendChild(head);
      var body = el('div', { style: 'flex:1;display:flex;flex-direction:column;min-height:0' });
      content.appendChild(body);
      activeRenderer = s.builder(body, head) || {};
      if (head.children.length === 0) head.remove();
      var cnt = activeRenderer.count ? activeRenderer.count() : 0;
      sectionHead.querySelector('.fg-count').textContent = cnt + (cnt === 1 ? ' entry' : ' entries');
      // Search only applies to list sections (those expose setQuery); hide it on form sections.
      var searchable = !!activeRenderer.setQuery;
      // keep the search box's flex space (invisible, not removed) so the titlebar buttons stay anchored right
      search.style.visibility = searchable ? 'visible' : 'hidden';
      if (searchable && search.value) activeRenderer.setQuery(search.value.trim());
      updateStatus();
    }
    function updateStatus() {
      var frozen = API.locks.summary().length;
      statusbar.innerHTML = '';
      statusbar.appendChild(el('span', { text: API.env.IS_MZ ? 'RPG Maker MZ' : 'RPG Maker MV' }));
      statusbar.appendChild(el('span', { class: 'fg-spacer', style: 'flex:1' }));
      statusbar.appendChild(el('span', { text: (frozen ? '🔒 ' + frozen + ' frozen · ' : '') + 'F10 to toggle' }));
    }

    search.addEventListener('input', debounce(function () { if (activeRenderer && activeRenderer.setQuery) activeRenderer.setQuery(search.value.trim()); }, 120));
    function debounce(fn, ms) { var t; return function () { clearTimeout(t); t = setTimeout(fn, ms); }; }

    // ---------- show / hide / hotkeys ----------
    var visible = false;
    function show() { visible = true; try { document.body.appendChild(host); } catch (e) {} panel.style.display = 'flex'; launcher.style.display = 'none'; if (!currentSection) selectSection(load('lastSection', 'vars')); else render(); }
    function hide() { visible = false; panel.style.display = 'none'; launcher.style.display = 'flex'; API.CHEAT.uiFocused = false; if (typeof Input !== 'undefined' && Input.clear) Input.clear(); }
    function toggle() { if (visible) hide(); else show(); }
    panel.style.display = 'none';

    // Speed key = HOLD to fast-forward: while the key is held the game runs at the armed boost speed;
    // on release it returns to 1x. Only active when the "use key" option is on. Gated to !uiFocused so
    // holding a key while typing in the panel never fast-forwards.
    var speedHeld = false;
    function isSpeedKey(k) { var sk = API._speedKey || 'Control'; return k === sk || (sk === 'Control' && k === 'Ctrl'); }
    function holdStart() { if (!speedHeld) { speedHeld = true; API.cheats.setSpeed(API._speedBoost || 2); toast('Fast-forward ' + API.CHEAT.speed + '×', 'ok'); } }
    function holdEnd() { if (speedHeld) { speedHeld = false; API.cheats.setSpeed(1); } }
    window.addEventListener('keydown', function (e) {
      if (API._capturingSpeedKey) return;                   // a key-rebind is in progress
      var key = e.key || '';
      if (key === (API._hotkey || 'F10')) { e.preventDefault(); toggle(); return; }
      if (visible && (e.ctrlKey || e.metaKey) && key.toLowerCase() === 'k') { e.preventDefault(); search.focus(); search.select(); }
      else if (visible && key === 'Escape') { if (shadow.activeElement && shadow.activeElement.tagName === 'INPUT') shadow.activeElement.blur(); else hide(); }
      if (API._speedUseKey && isSpeedKey(key) && !API.CHEAT.uiFocused) holdStart();   // hold to fast-forward
    }, true);
    window.addEventListener('keyup', function (e) {
      if (API._capturingSpeedKey) return;
      if (isSpeedKey(e.key || '')) holdEnd();
    }, true);
    window.addEventListener('blur', holdEnd);               // alt-tab / focus loss -> stop fast-forward (no stuck key)

    // expose
    return {
      show: show, hide: hide, toggle: toggle, toast: toast, render: render,
      isVisible: function () { return visible; }, root: rootEl, host: host,
      select: selectSection, sections: SECTIONS.map(function (s) { return s.id; })
    };
  }

})(typeof window !== 'undefined' ? window : (typeof globalThis !== 'undefined' ? globalThis : this));

/* ---- MZ scaffolding (registerCommand + start-open) ---- */
(function () {
  var P = (typeof PluginManager !== 'undefined' && PluginManager.parameters) ? PluginManager.parameters('Forge_MZ') : {};
  if (window.Forge) {
    window.Forge._hotkey = (P.hotkey || 'F10').trim();
    window.Forge._itemMaxOverride = Number(P.itemMaxOverride) || 0;
    window.Forge._uiScale = (P.uiScale || 'auto').trim();
    try { if (!localStorage.getItem('forge:speedKey')) window.Forge._speedKey = (P.speedKey || 'Control').trim(); } catch (e) { window.Forge._speedKey = (P.speedKey || 'Control').trim(); }
  }
  if (typeof PluginManager !== 'undefined' && PluginManager.registerCommand) {
    PluginManager.registerCommand('Forge_MZ', 'open', function () { if (window.Forge && window.Forge.ui) window.Forge.ui.toggle(); });
  }
  if (String(P.startOpen) === 'true' && typeof Scene_Map !== 'undefined') {
    var _s = Scene_Map.prototype.start;
    Scene_Map.prototype.start = function () { _s.call(this); if (window.Forge && window.Forge.ui && !window.Forge.ui.isVisible()) window.Forge.ui.show(); };
  }
})();

