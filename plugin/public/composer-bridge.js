"use strict";

// The same assembler shipped with the public Skill supplies the command.
// Only our same-origin parent can set public resource IDs and the draft text.
window.addEventListener("message", (event) => {
  if (
    event.source !== window.parent ||
    event.origin !== location.origin ||
    event.data?.type !== "handraw:compose"
  )
    return;
  const data = event.data;
  if (
    !Number.isSafeInteger(data.id) ||
    typeof data.theme !== "string" ||
    data.theme.length > 4000
  )
    return;
  currentLang = "zh";
  if (
    [
      "pure",
      "graphic-text",
      "poster",
      "article-cover",
      "article-illust",
      "photo",
    ].includes(data.mode)
  )
    setMode(data.mode);
  selectedStyle = STYLES_DATA.find((item) => item.id === data.style) || null;
  isFusionActive = data.fusion === true;
  checkboxFusion.checked = isFusionActive;
  selectedCharStyle = isFusionActive
    ? STYLES_DATA.find((item) => item.id === data.character_style) || null
    : null;
  selectedSceneStyle = isFusionActive
    ? STYLES_DATA.find((item) => item.id === data.scene_style) || null
    : null;
  if (
    isFusionActive &&
    (!selectedCharStyle ||
      !selectedSceneStyle ||
      selectedCharStyle.id === selectedSceneStyle.id)
  )
    return;
  selectedLayout = LAYOUTS_DATA.find((item) => item.id === data.layout) || null;
  selectedColor = COLORS_DATA.find((item) => item.id === data.color) || null;
  inputTheme.value = data.theme;
  const ratio = document.querySelector("#input-ratio");
  if (ratio)
    ratio.value = ["1:1", "3:4", "4:3", "16:9", "9:16"].includes(data.ratio)
      ? data.ratio
      : "1:1";
  const mood = document.querySelector("#input-mood");
  if (mood)
    mood.value = typeof data.mood === "string" ? data.mood.slice(0, 100) : "";
  updatePrompt();
  window.parent.postMessage(
    {
      type: "handraw:composed",
      id: data.id,
      command: assembledText.textContent,
    },
    event.origin,
  );
});
