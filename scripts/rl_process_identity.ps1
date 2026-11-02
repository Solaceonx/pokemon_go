# Convert JSON timestamps without losing a DateTime's existing UTC kind.
function Convert-RlRecordedStartToUtc([object]$Recorded) {
    if ($Recorded -is [DateTimeOffset]) { return $Recorded.UtcDateTime }
    if ($Recorded -is [DateTime]) { return $Recorded.ToUniversalTime() }
    return [DateTimeOffset]::Parse([string]$Recorded, [Globalization.CultureInfo]::InvariantCulture).UtcDateTime
}
