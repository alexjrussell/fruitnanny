"use strict";

import * as config from "../fruitnanny_config";
import custom_button from "./routes/custom_button";
import dht from "./routes/dht";
import express = require("express");
import enableWs = require("express-ws");
import light from "./routes/light";

let app = express();
var enabled = enableWs(app);
var wss = enabled.getWss('/messages');
app.ws('/messages', (ws, req) => {
    ws.on('message', msg => {
        console.log("Ignoring message from client: " + msg);
    })
    ws.on('close', () => {
        console.log('WebSocket was closed')
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

app.get("/sendmessage", (req: express.Request, res: express.Response, next: express.NextFunction) => {
    wss.clients.forEach(function each(client) {
        client.send(req.query.message);
    });
    res.sendStatus(200);
});
app.use("/api/light", light);
app.use("/api/dht", dht);
app.use("/api/custom_button", custom_button);

app.listen(7000, 'localhost', () => {
    console.log("Fruitnanny app listening on port 7000!");
});
