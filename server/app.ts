"use strict";

import * as config from "../fruitnanny_config";
import custom_button from "./routes/custom_button";
import dht from "./routes/dht";
import express = require("express");
import enableWs = require("express-ws");
import light from "./routes/light";
import * as cp from "child_process";

let app = express();
var enabled = enableWs(app);
var wss = enabled.getWss('/messages');

var recording = false;

app.ws('/messages', (ws, req) => {
    ws.on('message', msg => {
        if (msg == "shutdown") {
            console.log(new Date().toISOString() + " - Received shutdown request");
            cp.exec("sudo halt");
        } else if (msg == "isrecording") {
            ws.send("recording=" + recording);
        } else {
            console.log(new Date().toISOString() + " - Ignoring message from client: " + msg);
        }
    })
    ws.on('close', () => {
        console.log(new Date().toISOString() + ' - WebSocket was closed by client');
    })
});

app.set("view engine", "ejs");
app.set("views", "views");
app.use("/public", express.static("public"));

app.get("/", (req: express.Request, res: express.Response, next: express.NextFunction)  => {
  res.render("index", { config });
});

app.get("/settings", (req: express.Request, res: express.Response, next: express.NextFunction)  => {
    res.render("settings", { config });
  });

app.get("/notify", (req: express.Request, res: express.Response, next: express.NextFunction) => {
    if (req.query.type == "recording_started") {
        recording = true;
    } else if (req.query.type == "recording_ended") {
        recording = false;
    }
    wss.clients.forEach(function each(client) {
        client.send(req.query.type);
    });
    res.sendStatus(200);
});
app.use("/api/light", light);
app.use("/api/dht", dht);
app.use("/api/custom_button", custom_button);

app.listen(7000, 'localhost', () => {
    console.log(new Date().toISOString() + " - Fruitnanny app listening on port 7000!");
});
