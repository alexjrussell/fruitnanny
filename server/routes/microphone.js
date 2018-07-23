"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
const express = require("express");
const cp = require("child_process");
let router = express.Router();
router.get("/setlevel/:level", (req, res, next) => {
    cp.exec("bin/microphone,py " + req.params.level, (err, stdout, stderr) => {
        var level = stdout.trim();
        res.json(level);
    });
});
router.get("/getlevel", (req, res, next) => {
    cp.exec("bin/microphone,py", (err, stdout, stderr) => {
        var level = stdout.trim();
        res.json(level);
    });
});
exports.default = router;
