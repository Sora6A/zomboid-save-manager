require "ISUI/ISButton"

if _G.ZomboidSaveManagerBridgeLoaded then
    return
end
_G.ZomboidSaveManagerBridgeLoaded = true

local ZSM = {
    version = "1.1.8",
    commandFile = "ZomboidSaveManager_command.txt",
    statusFile = "ZomboidSaveManager_status.txt",
    button = nil,
    buttonPending = true,
    retryTicks = 0,
    buttonOffsetX = 58,
    buttonOffsetY = 110,
}

local function log(message)
    print("[ZomboidSaveManager] " .. tostring(message))
end

local function cleanField(value)
    value = tostring(value or "")
    value = string.gsub(value, "|", "_")
    value = string.gsub(value, "[\r\n]", " ")
    return value
end

local function writeSmallFile(fileName, value)
    local ok, err = pcall(function()
        local writer = getFileWriter(fileName, true, false)
        if not writer then error("getFileWriter returned nil") end
        writer:write(tostring(value))
        writer:close()
    end)
    if not ok then
        log("cannot write " .. fileName .. ": " .. tostring(err))
    end
    return ok
end

local function writeStatus(phase, detail)
    local value = ZSM.version .. "|" .. cleanField(phase) .. "|" .. cleanField(detail)
    writeSmallFile(ZSM.statusFile, value)
end

local function currentContext()
    local mode = ""
    local folder = ""
    pcall(function()
        local core = getCore()
        if core then
            mode = cleanField(core:getGameMode())
            folder = cleanField(core:getSaveFolder())
        end
    end)
    pcall(function()
        local world = getWorld()
        if world then
            if mode == "" then mode = cleanField(world:getGameMode()) end
            if folder == "" then folder = cleanField(world:getWorld()) end
        end
    end)
    return mode, folder
end

local function makeToken()
    local timestamp = 0
    local random = 0
    pcall(function()
        if getTimestampMs then
            timestamp = getTimestampMs()
        elseif getTimestamp then
            timestamp = getTimestamp()
        end
    end)
    pcall(function() random = ZombRand(1000000) end)
    return tostring(timestamp) .. "-" .. tostring(random)
end

local function sendCommand(action)
    local mode, folder = currentContext()
    local payload = makeToken() .. "|" .. action .. "|" .. mode .. "|" .. folder
    local ok = writeSmallFile(ZSM.commandFile, payload)
    if not ok then writeStatus("command_error", action) end
    return ok
end

local function notifyPlayer(message)
    pcall(function()
        local player = getPlayer()
        if player and HaloTextHelper then
            HaloTextHelper.addText(player, message, getCore():getGoodHighlitedColor())
        end
    end)
end

local function showManager()
    if sendCommand("SHOW") then
        notifyPlayer("Save manager opened (F8)")
    end
end

local function quickBackup()
    if sendCommand("BACKUP_AUTO") then
        notifyPlayer("Backup requested (F9)")
    end
end

local function positionButton()
    if not ZSM.button then return end
    local left = ZSM.buttonOffsetX
    local top = ZSM.buttonOffsetY
    pcall(function()
        left = getPlayerScreenLeft(0) + ZSM.buttonOffsetX
        top = getPlayerScreenTop(0) + ZSM.buttonOffsetY
    end)
    ZSM.button:setX(left)
    ZSM.button:setY(top)
    pcall(function() ZSM.button:bringToTop() end)
end

local function createButton()
    if ZSM.button then return true end
    if not getPlayer() then return false end

    local button = ISButton:new(
        ZSM.buttonOffsetX,
        ZSM.buttonOffsetY,
        42,
        32,
        "BK",
        ZSM,
        function()
        showManager()
        end
    )
    button:initialise()
    button:instantiate()
    pcall(function() button:setBackgroundRGBA(0.08, 0.12, 0.15, 0.82) end)
    pcall(function() button:setBackgroundColorMouseOverRGBA(0.18, 0.48, 0.28, 0.95) end)
    pcall(function() button:setBorderRGBA(0.68, 0.78, 0.70, 0.9) end)
    pcall(function() button:setTooltip("Save manager: F8 open, F9 quick backup") end)
    pcall(function() button:setEnable(true) end)
    pcall(function() button:setVisible(true) end)
    button:addToUIManager()
    pcall(function() button:bringToTop() end)
    ZSM.button = button
    positionButton()
    sendCommand("HELLO")
    writeStatus("ready", "BK/F8/F9")
    log("bridge ready: BK / F8 / F9")
    return true
end

local function requestButton()
    ZSM.buttonPending = true
    ZSM.retryTicks = 0
end

local function onTick()
    if not ZSM.buttonPending or ZSM.button then return end
    if ZSM.retryTicks > 0 then
        ZSM.retryTicks = ZSM.retryTicks - 1
        return
    end

    local ok, createdOrError = pcall(createButton)
    if ok and createdOrError then
        ZSM.buttonPending = false
        return
    end

    ZSM.retryTicks = 120
    if not ok then
        log("button creation failed: " .. tostring(createdOrError))
        writeStatus("button_error", createdOrError)
    end
end

local SHOW_KEY = 66
local BACKUP_KEY = 67
pcall(function()
    if Keyboard then
        SHOW_KEY = Keyboard.KEY_F8 or SHOW_KEY
        BACKUP_KEY = Keyboard.KEY_F9 or BACKUP_KEY
    end
end)

local function onKeyPressed(key)
    if key == SHOW_KEY then
        showManager()
    elseif key == BACKUP_KEY then
        quickBackup()
    end
end

local function removeButton()
    if ZSM.button then
        pcall(function() ZSM.button:removeFromUIManager() end)
        ZSM.button = nil
    end
    ZSM.buttonPending = false
end

log("client Lua loaded, version " .. ZSM.version)
writeStatus("lua_loaded", "waiting_for_player")
requestButton()
Events.OnGameStart.Add(requestButton)
if Events.OnCreatePlayer then Events.OnCreatePlayer.Add(requestButton) end
Events.OnTick.Add(onTick)
Events.OnKeyPressed.Add(onKeyPressed)
if Events.OnResolutionChange then Events.OnResolutionChange.Add(positionButton) end
if Events.OnGameExit then Events.OnGameExit.Add(removeButton) end
