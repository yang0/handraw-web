"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
assert.equal(fs.readFileSync("plugin/public/image-loader.js","utf8"),fs.readFileSync("demo/assets/image-loader.js","utf8"),"Gallery and application must ship the same responsive component");
require("./test_main_image_loader.cjs");
