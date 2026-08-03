# Renpy Cue

### Useful commands

Run in debug.log dir for color coded logs.

```ps
Get-Content debug.log -Wait | ForEach-Object {
    if ($_ -match "POOL-PLAY") {
        Write-Host $_ -ForegroundColor Red
    } elseif ($_ -match "CTX-TRIGGER|PLAY-SFX") {
        Write-Host $_ -ForegroundColor Green
    } elseif ($_ -match "CTX-CHANGE") {
        Write-Host $_ -ForegroundColor Cyan
    } else {
        Write-Host $_
    }
}
```