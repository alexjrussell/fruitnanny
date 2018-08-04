var Microphone = (function () {
    'use strict';

    var getlevel = function(callback) {
        $.get("/api/microphone/getlevel").
        done(function(data) {
            callback(data);
        }).fail(function(err) {
            console.log( "error: " + err );
        })
    }

    var setlevel = function(newlevel) {
        $.get("/api/microphone/setlevel/" + newlevel).
        done(function(data) {
            callback(data);
        }).fail(function(err) {
            console.log( "error: " + err );
        })
    }

    return {
        getlevel: getlevel,
        setlevel: setlevel
    }
}());
