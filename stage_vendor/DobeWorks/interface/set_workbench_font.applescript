on run arguments
    if (count of arguments) is not 1 then return
    tell application "Terminal"
    try
        set targetTab to missing value
        repeat with candidateWindow in windows
            repeat with candidateTab in tabs of candidateWindow
                if tty of candidateTab is item 1 of arguments then set targetTab to contents of candidateTab
            end repeat
        end repeat
        if targetTab is missing value then return
        if exists settings set "DobeWorks" then
            set current settings of targetTab to settings set "DobeWorks"
        end if
        set font name of targetTab to "Courier"
        set font size of targetTab to 13
        set font antialiasing of targetTab to true
        set number of columns of targetTab to 72
        set number of rows of targetTab to 30
        set custom title of targetTab to "DobeWorks"
        set title displays custom title of targetTab to true
        set title displays device name of targetTab to false
        set title displays shell path of targetTab to false
        set title displays window size of targetTab to false
        set title displays file name of targetTab to false
    end try
    end tell
end run
