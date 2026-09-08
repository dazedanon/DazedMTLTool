/* Keep player saves working across translation patch updates.
 *
 * A TyranoScript save records where it was as `data.current_order_index`, an
 * integer index into the *parsed element array* of the current scenario file,
 * and `loadGameData` resumes with `nextOrderWithIndex(that index, ...)`.
 *
 * That index is not stable across a text patch. Every `[r]` the layout pass
 * drops or inserts, and every tag it removes, changes how many elements the
 * file parses to - so a save taken later in an edited file resumes at the wrong
 * element. Without this, every patch release would cost players their saves.
 *
 * What is stable is the *source line*: injection is a span splice and every
 * edit the pipeline makes happens within a line, so line numbers survive. The
 * fix is therefore to record the position by line rather than by index, and to
 * re-derive the index on load.
 *
 * Two levels of precision:
 *
 *   new saves     `snapSave` is wrapped to stamp `data.__compat` with the line,
 *                 the element's ordinal *within* that line, and its kind. On
 *                 load that identifies the element exactly, even on a line whose
 *                 element count changed.
 *
 *   older saves   nothing stamped, so it falls back to `stat.current_line` and
 *                 picks the element on that line nearest the stored index.
 *
 * Measured with `scratchpad/test_remap.js` over all 22 scenarios this patch
 * shifted - 24,019 elements, every one treated as a save point:
 *
 *     no remap (what a plain patch does)   63.2% land on the right element
 *     older save, line only                85.4%, and never the wrong line
 *     stamped save, line + ordinal         99.2%, and never the wrong line
 *
 * The 0.8% are lines whose element composition the patch itself changed - two
 * text runs merged where an `[r]` came out - and there landing on the merged
 * element is the right answer, not a miss.
 *
 * Design notes:
 *
 *   - It patches the prototypes `tyrano.plugin.kag.menu` and `.ftag`. `kag.init`
 *     clones both with `object()` at DOM ready, so a patch applied by a script
 *     before </body> is inherited by the live instances. No polling.
 *
 *   - The remap runs only on the save-load path. `nextOrderWithIndex` is also
 *     how a macro returns to its caller, and there the recorded line refers to
 *     somewhere else entirely - remapping that would break the game. A flag set
 *     by `loadGameData` and consumed by the very next `nextOrderWithIndex` call
 *     keeps the two apart.
 *
 *   - It corrects the index *before* the original runs, because the original
 *     splices its `make.ks` call at `index + 1`.
 *
 *   - When nothing has moved it returns the index untouched, so an unpatched
 *     game and a freshly made save both take a path that changes nothing.
 *
 *   - Anything unexpected falls back to the stored index, which is the
 *     behaviour without this file. It can degrade; it should not break a load.
 */
(function () {
  'use strict';

  var TAG = '[save-compat]';
  var state = { installed: false, remaps: 0, last: null };

  /* Where the element sits, in terms that survive a text patch. */
  function describe(ftag) {
    try {
      var index = ftag.current_order_index;
      var array_tag = ftag.array_tag;
      var here = array_tag && array_tag[index];
      if (!here) return null;
      var ordinal = 0;
      for (var i = index - 1; i >= 0 && array_tag[i].line === here.line; i--) {
        ordinal++;
      }
      return { v: 1, line: here.line, ordinal: ordinal, name: here.name };
    } catch (err) {
      return null;
    }
  }

  /* How many elements before this one share its line. */
  /* How far, in elements, a resume point may have drifted and still be the
   * same tag. A patch moves things by one or two; anything further is a
   * rewrite, and guessing across it would resume in the wrong scene. */
  var DRIFT = 16;

  function ordinalOf(array_tag, index) {
    var ordinal = 0;
    for (var i = index - 1; i >= 0 && array_tag[i] &&
         array_tag[i].line === array_tag[index].line; i--) {
      ordinal++;
    }
    return ordinal;
  }

  /* Tags that clear the message box. The run of text since the last one is
   * what stands on screen, which is what `current_message_str` recorded. */
  var CLEARS = { p: 1, cm: 1, er: 1, ct: 1 };

  /* Where a save can have been taken: the engine writes one while waiting. */
  var WAITS = { s: 1, p: 1, l: 1, lr: 1 };

  function normalise(text) {
    if (typeof text !== 'string') return '';
    return text.replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();
  }

  /* The message standing on screen when execution reaches `at`. */
  function messageAt(array_tag, at) {
    var parts = [];
    for (var i = at - 1; i >= 0; i--) {
      var name = array_tag[i].name;
      if (name === 'text') parts.unshift(array_tag[i].val || '');
      else if (CLEARS[name]) break;
    }
    return normalise(parts.join(''));
  }

  /* The one wait point whose message is the message the save recorded.
   *
   * A patch that adds or drops lines leaves the line number pointing at the
   * wrong place, and one [p] looks exactly like the next - but the text in
   * front of it does not. Only a *unique* match is accepted; anything repeated
   * verbatim elsewhere in the file falls through to the line logic, which is
   * the more precise answer whenever the line survived.
   */
  function byMessage(array_tag, mark) {
    var wanted = normalise(mark && mark.message);
    if (!wanted || wanted.length < 4) return -1;
    var found = -1;
    for (var i = 0; i < array_tag.length; i++) {
      if (!WAITS[array_tag[i].name]) continue;
      if (mark.name !== undefined && array_tag[i].name !== mark.name) continue;
      if (messageAt(array_tag, i) !== wanted) continue;
      if (found >= 0) return -1;                      // ambiguous, do not guess
      found = i;
    }
    return found;
  }

  /* The element that was executing sits one past the stored index: snapSave
   * stores `current_order_index - 1`, and load calls nextOrder() once. */
  function remap(array_tag, saved, mark) {
    if (!array_tag || !array_tag.length || !mark) return saved;
    var want = saved + 1;

    var here = array_tag[want];
    if (here && here.line === mark.line &&
        (mark.name === undefined || here.name === mark.name) &&
        (mark.ordinal === undefined || ordinalOf(array_tag, want) === mark.ordinal)) {
      return saved;                                   // nothing moved
    }

    /* The recorded position is wrong. Before guessing from it, look for the
     * text the save had on screen: it survives lines moving, and it is in
     * every save regardless of whether this shim wrote the stamp. */
    var byText = byMessage(array_tag, mark);
    if (byText >= 0) return byText - 1;

    var candidates = [];
    for (var i = 0; i < array_tag.length; i++) {
      if (array_tag[i].line === mark.line) candidates.push(i);
    }
    if (!candidates.length) {
      /* The tag moved to another line, so nothing sits on the recorded one any
       * more. Its name and its place within its own line still identify it, so
       * take the nearest match to where it used to be. Without this the raw
       * index is used unchanged, which lands one element off after any patch
       * that adds or drops a tag earlier in the file: a save left waiting on
       * [s] then resumes on the label after it and plays the scene. */
      if (mark.name === undefined) return saved;
      for (var step = 0; step <= DRIFT; step++) {
        for (var side = 0; side < 2; side++) {
          var at = side ? want - step : want + step;
          if (at < 0 || at >= array_tag.length) continue;
          if (array_tag[at].name === mark.name &&
              (mark.ordinal === undefined ||
               ordinalOf(array_tag, at) === mark.ordinal)) {
            return at - 1;
          }
        }
      }
      return saved;                                   // nowhere near: give up
    }

    if (typeof mark.ordinal === 'number') {
      var exact = candidates[mark.ordinal];
      if (exact !== undefined &&
          (mark.name === undefined || array_tag[exact].name === mark.name)) {
        return exact - 1;
      }
    }

    var best = candidates[0];
    var bestDistance = Infinity;
    for (var j = 0; j < candidates.length; j++) {
      var distance = Math.abs(candidates[j] - want);
      if (distance < bestDistance) {
        bestDistance = distance;
        best = candidates[j];
      }
    }
    return best - 1;
  }

  function install() {
    if (typeof tyrano === 'undefined' || !tyrano.plugin || !tyrano.plugin.kag) {
      return false;
    }
    var proto = tyrano.plugin.kag;
    if (!proto.menu || !proto.ftag || state.installed) return false;

    var snapSave = proto.menu.snapSave;
    proto.menu.snapSave = function (title, call_back, flag_thumb) {
      var self = this;
      var mark = describe(this.kag.ftag);
      var stamp = function () {
        try {
          if (self.snap && mark) self.snap.__compat = mark;
        } catch (err) { /* the save is still valid without it */ }
        if (typeof call_back === 'function') call_back();
      };
      return snapSave.call(this, title, stamp, flag_thumb);
    };

    var loadGameData = proto.menu.loadGameData;
  /* A save stores the whole of `f`, and this game keeps its tables there:
   * f.task, f.item and the rest are filled in from exp.ks when a game is
   * *started* and then travel with the save forever. Translate a name after
   * that and every existing save keeps the old one - which is why a finished
   * task still read 完了したタスク in a save begun before that string was
   * translated.
   *
   * So write the build's own copy back over the save's. What ships is chosen in
   * tyranotl/savetext.py and holds only fields that are purely display text; a
   * task name that doubles as a jump target is deliberately not among them.
   * Three guards on top of that: the table has to still have the same number of
   * rows, the value being replaced has to already be a string, and a row the
   * build has nothing for is left alone. */
  function refreshText(f) {
    var data = window.__saveText;
    if (!f || !data) return 0;
    var written = 0;
    for (var name in data) {
      var table = f[name];
      var columns = data[name];
      if (!table || typeof table.length !== 'number') continue;

      var fields = Object.keys(columns);
      if (!fields.length || columns[fields[0]].length !== table.length) {
        console.log(TAG + ' f.' + name + ' has a different shape in this save, ' +
                    'leaving its text alone');
        continue;
      }
      for (var at = 0; at < fields.length; at++) {
        var field = fields[at];
        var values = columns[field];
        for (var i = 0; i < values.length; i++) {
          var row = table[i];
          if (!row || values[i] === null) continue;
          if (typeof row[field] !== 'string' || row[field] === values[i]) continue;
          row[field] = values[i];
          written++;
        }
      }
    }
    return written;
  }

  /* A macro is registered as {storage, index} - an *element index* into the
   * file that defines it - and map_macro lives in kag.stat, which the save
   * stores wholesale. So a save carries the macro table of the build it was
   * made on, and loading it installs those indices over the current build.
   * Any patch that changes the element count of macro.ks then sends every
   * macro defined after the change to the wrong tags: the screen a button
   * opens half-builds itself out of the tail of the previous macro.
   *
   * The engine parses macro.ks at boot, so the table already in memory is
   * correct for the build that is running. Prefer it, entry by entry, and keep
   * saved entries only for macros this session has not registered yet - those
   * get corrected anyway when their file is parsed. */
  function freshMacros(live, saved) {
    if (!live) return saved;
    if (!saved) return live;
    var merged = {}, name;
    for (name in saved) merged[name] = saved[name];
    for (name in live) merged[name] = live[name];
    return merged;
  }

    proto.menu.loadGameData = function (data) {
      var mark = null;
      try {
        if (data && data.__compat && typeof data.__compat.line === 'number') {
          mark = data.__compat;
        } else if (data && data.stat && typeof data.stat.current_line === 'number') {
          mark = { v: 0, line: data.stat.current_line };
        }
        if (mark && data.stat && typeof data.stat.current_message_str === 'string') {
          mark.message = data.stat.current_message_str;
        }
      } catch (err) { mark = null; }
      try { this.kag.ftag.__resumeMark = mark; } catch (err) { /* ignore */ }
      try {
        if (data && data.stat) {
          var live = this.kag.stat && this.kag.stat.map_macro;
          var before = data.stat.map_macro;
          data.stat.map_macro = freshMacros(live, before);
          if (live && before) {
            var moved = 0;
            for (var name in before) {
              if (live[name] && live[name].index !== before[name].index) moved++;
            }
            if (moved) {
              state.macros = moved;
              console.log(TAG + ' ' + moved + ' macro indices in this save are ' +
                          'from an older build, using the current table');
            }
          }
        }
        var written = refreshText(data.stat && data.stat.f);
        if (written) {
          state.text = written;
          console.log(TAG + ' refreshed ' + written +
                      ' text fields this save had an older version of');
        }
      } catch (err) { console.log(TAG + ' could not refresh saved data', err); }
      return loadGameData.apply(this, arguments);
    };

    var nextOrderWithIndex = proto.ftag.nextOrderWithIndex;
    proto.ftag.nextOrderWithIndex = function (index, scenario_file) {
      var mark = this.__resumeMark;
      this.__resumeMark = null;
      if (!mark || typeof index !== 'number') {
        return nextOrderWithIndex.apply(this, arguments);
      }

      var self = this;
      var args = Array.prototype.slice.call(arguments);
      var file = scenario_file || this.kag.stat.current_scenario;
      try {
        // loadScenario caches by URL, so this costs a lookup, not a read
        this.kag.loadScenario(file, function (array_tag) {
          var fixed = index;
          try {
            fixed = remap(array_tag, index, mark);
          } catch (err) {
            console.log(TAG + ' remap failed, keeping the stored index', err);
          }
          if (fixed !== index) {
            state.remaps++;
            state.last = { file: file, mark: mark, from: index, to: fixed };
            console.log(TAG + ' ' + file + ': resume index ' + index + ' -> ' +
                        fixed + ' (source line ' + mark.line + ')');
          }
          args[0] = fixed;
          nextOrderWithIndex.apply(self, args);
        });
      } catch (err) {
        console.log(TAG + ' could not re-read the scenario, keeping the stored index', err);
        nextOrderWithIndex.apply(self, args);
      }
    };

    state.installed = true;
    window.__saveCompat = state;
    console.log(TAG + ' installed');
    return true;
  }

  if (!install()) {
    // The engine should already be defined - every kag script is in <head> -
    // but do not take the game down if the load order ever changes.
    console.log(TAG + ' engine not ready; saves will use the stored index');
  }
})();
