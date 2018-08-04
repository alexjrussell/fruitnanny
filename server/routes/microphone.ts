"use strict";

import express = require("express");
import * as cp from "child_process";
let router = express.Router();

router.get("/setlevel/:level", (req: express.Request, res: express.Response, next: express.NextFunction) => {
    cp.exec("bin/microphone,py " + req.params.level, (err, stdout, stderr) => {
        let level = stdout.trim();
        res.json(level);
    });
});

router.get("/getlevel", (req: express.Request, res: express.Response, next: express.NextFunction) => {
    cp.exec("bin/microphone,py", (err, stdout, stderr) => {
        let level = stdout.trim();
        res.json(level);
    });
});

export default router;
