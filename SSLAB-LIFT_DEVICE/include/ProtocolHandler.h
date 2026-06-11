#pragma once

#include <Arduino.h>
#include <ArduinoJson.h>

// Callback function types for device actions
// Add more callbacks here for different device types
typedef std::function<bool(bool status, JsonObject& result)> ComputerControlCallback;
typedef std::function<bool(bool status, int brightness, JsonObject& result)> LampControlCallback;
typedef std::function<bool(const String& value, JsonObject& result)> LiftingControlCallback;
typedef std::function<bool(const String& group, JsonObject& result)> SetGroupCallback;

class ProtocolHandler {
public:
    ProtocolHandler();

    void setComputerControlCallback(ComputerControlCallback cb);
    void setLampControlCallback(LampControlCallback cb);
    void setLiftingControlCallback(LiftingControlCallback cb);
    void setGroupCallback(SetGroupCallback cb);

    // Process a request. 
    // requestId: from MQTT topic or Serial generated
    // method: from JSON
    // params: from JSON
    // responseDoc: output JSON document for the response
    void processRequest(const String& requestId, const String& method, const JsonObject& params, JsonDocument& responseDoc);

private:
    ComputerControlCallback _computerControlCb;
    LampControlCallback _lampControlCb;
    LiftingControlCallback _liftingControlCb;
    SetGroupCallback _setGroupCb;
};
