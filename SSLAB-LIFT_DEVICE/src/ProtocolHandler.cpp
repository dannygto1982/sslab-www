#include "ProtocolHandler.h"
#include <time.h>

ProtocolHandler::ProtocolHandler() {}

void ProtocolHandler::setComputerControlCallback(ComputerControlCallback cb) {
    _computerControlCb = cb;
}

void ProtocolHandler::setLampControlCallback(LampControlCallback cb) {
    _lampControlCb = cb;
}

void ProtocolHandler::setLiftingControlCallback(LiftingControlCallback cb) {
    _liftingControlCb = cb;
}

void ProtocolHandler::setGroupCallback(SetGroupCallback cb) {
    _setGroupCb = cb;
}

void ProtocolHandler::processRequest(const String& requestId, const String& method, const JsonObject& params, JsonDocument& responseDoc) {
    // Prepare common response structure
    // v3.2 Response: { "success": true, "result": {}, "error": {} }
    
    bool success = false;
    String errorMessage = "";
    
    // Add timestamp (Epoch ms)
    responseDoc["timestamp"] = time(nullptr) * 1000LL; 

    // [Serial.printf removed] 不输出 method 到串口，防止污染 RS485 总线

    // Prepare result object for callbacks to fill
    JsonObject resultObj = responseDoc["result"].to<JsonObject>();

    if (method == "controlComputer") {
        if (_computerControlCb) {
            // Strict check: must be boolean as per protocol
            if (params["status"].is<bool>()) {
                bool status = params["status"];
                success = _computerControlCb(status, resultObj);
                if (!success) {
                    errorMessage = "Failed to execute controlComputer";
                }
            } else {
                errorMessage = "Missing or invalid 'status' parameter (must be boolean)";
            }
        } else {
            errorMessage = "Callback not registered";
        }
    }
    else if (method == "controlLamp") {
        if (_lampControlCb) {
            // Strict check: must be boolean as per protocol
            if (params["status"].is<bool>()) {
                bool status = params["status"];
                int brightness = params["brightness"].is<int>() ? params["brightness"].as<int>() : -1;
                success = _lampControlCb(status, brightness, resultObj);
                if (!success) {
                    errorMessage = "Failed to execute controlLamp";
                }
            } else {
                errorMessage = "Missing or invalid 'status' parameter (must be boolean)";
            }
        } else {
            errorMessage = "Callback not registered";
        }
    }
    else if (method == "controlLifting") {
        if (_liftingControlCb) {
            if (params["value"].is<const char*>()) {
                String value = params["value"];
                value.toLowerCase();
                if (value == "up" || value == "down" || value == "stop") {
                    success = _liftingControlCb(value, resultObj);
                    if (!success) {
                        errorMessage = "Failed to execute controlLifting";
                    }
                } else {
                    errorMessage = "Invalid 'value' parameter (must be up/down/stop)";
                }
            } else if (params["value"].is<bool>()) {
                bool value = params["value"];
                success = _liftingControlCb(value ? "up" : "down", resultObj);
                if (!success) {
                    errorMessage = "Failed to execute controlLifting";
                }
            } else {
                errorMessage = "Missing or invalid 'value' parameter";
            }
        } else {
            errorMessage = "Callback not registered";
        }
    }
    else if (method == "setGroup") {
        if (_setGroupCb) {
            if (params["studentGroup"].is<const char*>()) {
                String group = params["studentGroup"];
                success = _setGroupCb(group, resultObj);
                if (!success) {
                    errorMessage = "Failed to execute setGroup";
                }
            } else {
                errorMessage = "Missing or invalid 'studentGroup' parameter";
            }
        } else {
            errorMessage = "Callback not registered";
        }
    }
    else if (method == "ping") {
        success = true;
        // resultObj is already created at the top
        resultObj["pong"] = millis();
    }
    else {
        errorMessage = "Method not supported: " + method;
    }

    responseDoc["success"] = success;
    
    if (success) {
        // If callback didn't add anything to result, add a default message
        if (resultObj.size() == 0) {
            resultObj["message"] = "Operation successful";
        }
    } else {
        JsonObject error = responseDoc["error"].to<JsonObject>();
        error["code"] = 400;
        error["message"] = errorMessage.isEmpty() ? "Unknown error" : errorMessage;
    }
}
