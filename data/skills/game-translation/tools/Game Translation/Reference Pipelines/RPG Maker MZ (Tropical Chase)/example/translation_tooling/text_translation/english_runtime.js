/* Tropical Chase English: save-display compatibility and results layout.
 * No network calls, logging, telemetry or save-file writes.
 * Cached event command lists and their resume indices are intentionally preserved.
 */
(() => {
  'use strict';
  const originalReadText = __ORIGINAL_READ_TEXT__;
  const actorNames = __ACTOR_NAMES__;
  const displayValues = __DISPLAY_VALUES__;
  const load = DataManager.extractSaveContents;
  DataManager.extractSaveContents = function(contents) {
    load.apply(this, arguments);
    for (const [id, oldName, english] of actorNames) {
      const actor = $gameActors._data[id];
      if (actor && actor._name === oldName) actor._name = english;
    }
    for (const [id, oldValue, english] of displayValues) {
      if ($gameVariables._data[id] === oldValue) $gameVariables._data[id] = english;
    }
  };
  // Use the source text as the stable read-history key. The existing plugin
  // expressly supports an original-text override, so old read flags still work.
  const show = Game_Interpreter.prototype.command101;
  Game_Interpreter.prototype.command101 = function() {
    if (!$gameMessage.isBusy()) {
      const info = this.currentCommand()?.SkipAlreadyReadMessage?.info;
      if (info) {
        const key = [info.map, info.event, info.page, this._index].join('/');
        const text = originalReadText[key];
        if (text !== undefined) {
          const state = $gameMessage.SkipAlreadyReadMessage ||= {};
          state.org_text = text;
        }
      }
    }
    return show.apply(this, arguments);
  };
  // CE30 draws text over a painted rectangle inside a full-screen image.
  // The rectangle, not the image canvas or viewport, bounds the results.
  // Widen only that rectangle; retain the original gradient, alpha and title.
  const updatePicture = Sprite_Picture.prototype.update;
  Sprite_Picture.prototype.update = function() {
    updatePicture.apply(this, arguments);
    const resultsMap = [4, 14].includes($gameMap.mapId());
    if (this._englishResultsBackground && (!resultsMap || this._pictureName !== 'result_back')) {
      if (this.bitmap === this._englishResultsBackground) {
        this.bitmap = this.visible ? ImageManager.loadPicture(this._pictureName) : null;
      }
      this._englishResultsBackground.destroy();
      this._englishResultsBackground = null;
    }
    if (!resultsMap || !this.visible || !this.bitmap?.isReady()) return;
    if (this._pictureId === 1 && this._pictureName === 'result_back') {
      if (!this._englishResultsBackground) {
        const source = this.bitmap;
        const expanded = new Bitmap(source.width, source.height);
        expanded.blt(source, 0, 0, source.width, source.height, 0, 0);
        expanded.clearRect(185, 94, 439, 431);
        expanded.blt(source, 185, 94, 439, 431, 88, 94, 640, 431);
        this._englishResultsBackground = expanded;
      }
      this.bitmap = this._englishResultsBackground;
    } else if (this._pictureId === 10 && this.picture()?.mzkp_text &&
               $gameScreen.picture(1)?.name() === 'result_back') {
      // Keep normal results at their original size. Exceptionally large totals
      // scale uniformly, within the panel's side and bottom padding.
      const scale = Math.min(1, 592 / this.bitmap.width, 401 / this.bitmap.height);
      this.scale.set(scale, scale);
      this.x = Math.round((816 - this.bitmap.width * scale) / 2);
    }
  };
  const destroyPicture = Sprite_Picture.prototype.destroy;
  Sprite_Picture.prototype.destroy = function() {
    const owned = this._englishResultsBackground;
    destroyPicture.apply(this, arguments);
    if (owned) owned.destroy();
  };
})();
