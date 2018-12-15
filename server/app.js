"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
const config = require("../fruitnanny_config");
const custom_button_1 = require("./routes/custom_button");
const dht_1 = require("./routes/dht");
const express = require("express");
const enableWs = require("express-ws");
const light_1 = require("./routes/light");
const cp = require("child_process");
let app = express();
var enabled = enableWs(app);
var wss = enabled.getWss('/messages');
var recording = false;
app.ws('/messages', (ws, req) => {
    ws.on('message', msg => {
        if (msg == "shutdown") {
            console.log(new Date().toISOString() + "Received shutdown request");
            cp.exec("sudo halt");
        }
        else if (msg == "isrecording") {
            ws.send("recording=" + recording);
        }
        else {
            console.log(new Date().toISOString() + "Ignoring message from client: " + msg);
        }
    });
    ws.on('close', () => {
        console.log(new Date().toISOString() + 'WebSocket was closed by client');
    });
});
app.set("view engine", "ejs");
app.set("views", "views");
app.use("/public", express.static("public"));
app.get("/", (req, res, next) => {
    res.render("index", { config });
});
app.get("/settings", (req, res, next) => {
    res.render("settings", { config });
});
app.get("/notify", (req, res, next) => {
    if (req.query.type == "recording_started") {
        recording = true;
    }
    else if (req.query.type == "recording_ended") {
        recording = false;
    }
    wss.clients.forEach(function each(client) {
        client.send(req.query.type);
    });
    res.sendStatus(200);
});
app.use("/api/light", light_1.default);
app.use("/api/dht", dht_1.default);
app.use("/api/custom_button", custom_button_1.default);
app.listen(7000, 'localhost', () => {
    console.log("Fruitnanny app listening on port 7000!");
});
