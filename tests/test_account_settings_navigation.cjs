/* Regression guard for the standalone account P1 navigation and auth UX. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const root = path.join(__dirname, "..");
const main = fs.readFileSync(path.join(root, "demo/assets/main-app.js"), "utf8");
const shared = fs.readFileSync(path.join(root, "demo/assets/shared.js"), "utf8");

assert.match(main, /function renderAccountSettingsPage\(root\)/, "account settings has its own view");
assert.match(main, /view === "account" \|\| \(view === "profile" && p\.get\("ptab"\) === "account"\)/, "legacy profile account URLs redirect");
assert.match(main, /App\.view === "account"\) renderAccountSettingsPage\(root\)/, "account route renders settings");
assert.match(main, /UI\.accountSection = snap\.accountSection \|\| UI\.accountSection/, "auth returns to selected account section");
assert.match(main, /node\.dataset\.accountPanel !== section\) node\.remove\(\)/, "irrelevant account panels are removed");
for (const panel of ["profile","security","devices"]) {
  assert.match(shared, new RegExp('data-account-panel="'+panel+'"'), panel + " section defined");
}
assert.match(shared, /id="acc-avatar-confirm"/, "avatar requires explicit confirmation");
assert.match(shared, /id="acc-avatar-confirm"/, "avatar requires explicit confirmation");
assert.match(shared, /pendingAvatar = file/, "selection only stages the avatar until confirmation");
assert.match(shared, /avatarPreview\\.toDataURL\\("image\\/png"\\)/, "uploads exactly the approved crop");
assert.match(shared, /createImageBitmap\\(file/, "large PNG source supports native decoding");
assert.match(shared, /reader\\.readAsDataURL\\(file\\)/, "browser decoding fallback exists");
assert.match(shared, /id="acc-avatar-upload-preview"[^\n]*tabindex="0"/, "crop can be controlled from keyboard");
assert.match(shared, /pointerdown/, "pointer drag starts");
assert.match(shared, /pointermove/, "pointer drag updates crop position");
assert.match(shared, /pointerup/, "pointer drag ends");
assert.match(shared, /avatarPanX \\+= dx/, "drag follows pointer direction");
assert.match(shared, /id="acc-avatar-center"/, "crop can be recentered");
assert.match(shared, /restoreAuthDraft\\(\\)/, "authentication drafts survive tab switching");
assert.match(shared, /event\\.key !== "Enter"/, "auth forms support Enter");
assert.doesNotMatch(main, /data-ptab="account"/, "account settings is separate from public profile");
assert.match(shared, /注册昵称与邀请码（选填）/, "registration nickname and invite code remain optional");
assert.match(shared, /注册完成后昵称不可修改/, "registration explains nickname permanence");
assert.doesNotMatch(shared, /id="acc-display-name"/, "existing nickname is not editable");
assert.doesNotMatch(shared, /data-account-panel="privacy"/, "account closure section is not exposed");
assert.doesNotMatch(shared, /\\/api\\/account\\/close/, "client does not call closure API");
assert.doesNotMatch(main, /"reactivate"/, "closed account recovery page is not routed");
assert.match(shared, /data-account-panel="email"/, "email verification has its own section");
assert.match(shared, /id="acc-send-email-verification"/, "email verification is on the email page");
assert.match(shared, /body: \{ currentPassword, newPassword \}/, "password change remains separate from profile update");
assert.doesNotMatch(shared.slice(shared.indexOf("function renderAccountSettingsFormHtml"), shared.indexOf("function bindAccountSettingsForm")), /view:"recovery"/, "recovery entry is only in logged-out flow");
console.log("Account navigation / registration regression guards passed");
