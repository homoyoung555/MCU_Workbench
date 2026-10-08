param(
    [string]$Workbook = (Join-Path $PSScriptRoot "..\test_data\program_PCD009_V0.9_V1.3.xlsx")
)

$ErrorActionPreference = "Stop"
$workbookPath = [System.IO.Path]::GetFullPath($Workbook)
if (-not [System.IO.File]::Exists($workbookPath)) {
    throw "Workbook not found: $workbookPath"
}

$excel = $null
$book = $null
try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $book = $excel.Workbooks.Open($workbookPath)

    $flow = $book.Worksheets.Item("FLOW")
    $pattern = $book.Worksheets.Item("pattern")

    $headers = @{}
    for ($column = 1; $column -le $flow.UsedRange.Columns.Count; $column++) {
        $name = [string]$flow.Cells.Item(1, $column).Value2
        if ($name) { $headers[$name] = $column }
    }
    foreach ($required in @("CP NO", "item", "type", "Recipe")) {
        if (-not $headers.ContainsKey($required)) {
            throw "FLOW missing required column: $required"
        }
    }

    $dependentItems = @("Hsi_8M", "Hsi_16M", "Hsi_24M", "Hsi_48M")
    $updatedRecipes = 0
    for ($row = 2; $row -le $flow.UsedRange.Rows.Count; $row++) {
        $cp = [string]$flow.Cells.Item($row, $headers["CP NO"]).Value2
        $item = [string]$flow.Cells.Item($row, $headers["item"]).Value2
        $type = [string]$flow.Cells.Item($row, $headers["type"]).Value2
        if ($type -ne "trim") { continue }

        if ($item -eq "Hsi_Vrega") {
            $flow.Cells.Item($row, $headers["Recipe"]).Value2 = "ENTER`nTRIM`nDAC_ADJ(<1.16:+1)`nJUDGE"
            $updatedRecipes++
        }
        elseif (($cp -eq "CP1" -or $cp -eq "CP3") -and $dependentItems -contains $item) {
            $flow.Cells.Item($row, $headers["Recipe"]).Value2 = "ENTER`nDEPEND(Hsi_Vrega)`nTRIM`nJUDGE"
            $updatedRecipes++
        }
    }

    $removedLinks = 0
    $logicalItem = ""
    for ($row = 2; $row -le $pattern.UsedRange.Rows.Count; $row++) {
        $cellItem = [string]$pattern.Cells.Item($row, 1).Value2
        if ($cellItem) { $logicalItem = $cellItem }
        $description = [string]$pattern.Cells.Item($row, 3).Value2
        $role = [string]$pattern.Cells.Item($row, 4).Value2
        if ($dependentItems -contains $logicalItem -and $description -eq "Hsi_Vrega" -and $role -eq "reuse dac") {
            $pattern.Cells.Item($row, 3).ClearContents()
            $pattern.Cells.Item($row, 4).ClearContents()
            $removedLinks++
        }
    }

    $recipeColumn = $flow.Columns.Item($headers["Recipe"])
    $recipeColumn.ColumnWidth = 24
    $recipeColumn.WrapText = $true
    $flow.UsedRange.Rows.AutoFit() | Out-Null

    if ($headers.ContainsKey("DAC ADJ")) {
        $flow.Columns.Item($headers["DAC ADJ"]).Delete() | Out-Null
        Write-Output "Deleted FLOW column: DAC ADJ"
    }
    else {
        Write-Output "FLOW column already absent: DAC ADJ"
    }
    $book.Save()
    Write-Output "Updated Recipe rows: $updatedRecipes"
    Write-Output "Removed Pattern reuse links: $removedLinks"
}
finally {
    if ($book -ne $null) { $book.Close($false) }
    if ($excel -ne $null) { $excel.Quit() }
    if ($pattern -ne $null) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($pattern) }
    if ($flow -ne $null) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($flow) }
    if ($book -ne $null) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($book) }
    if ($excel -ne $null) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($excel) }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
