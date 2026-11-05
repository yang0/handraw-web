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
assert.match(shared, /pendingAvatar = file/, "selected avatar is only pending until confirmed");
assert.match(shared, /avatarPreview\.toDataURL\("image\/png"\)/, "uploaded avatar uses approved square crop");
assert.match(shared, /restoreAuthDraft\(\)/, "authentication drafts survive tab switching");
assert.match(shared, /event\.key !== "Enter"/, "auth forms support Enter submission");
assert.doesNotMatch(main, /data-ptab="account"/, "account settings is not a public profile tab");
assert.match(shared, /创作者资料与邀请码（选填）/, "registration optional identity fields are collapsed");
assert.match(shared, /if \(displayName\) \{[\s\S]*?payload\.displayName = displayName/, "empty nickname does not prevent bio save");
assert.match(shared, /body: \{ currentPassword, newPassword \}/, "password change remains separate from profile update");
assert.doesNotMatch(shared.slice(shared.indexOf("function renderAccountSettingsFormHtml"), shared.indexOf("function bindAccountSettingsForm")), /view:"recovery"/, "recovery entry is only in logged-out flow");
console.log("Account navigation / registration regression guards passed");
