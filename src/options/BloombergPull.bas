Attribute VB_Name = "BloombergPull"
'================================================================
' BloombergPull - FX futures options dataset puller (Bloomberg DAPI)
'
' Requires: Bloomberg Terminal logged in on this machine
'           + Bloomberg Excel Add-in (BLP / BQNT) installed and enabled.
' Driven via the add-in worksheet functions (BDH/BDP/BDS) from VBA,
' with async-query waiting. Pulls die without an active Terminal session.
'
' What it gets:
'   1. Daily settlement history for the 6 CME FX majors (slope/Bollinger/underlying)
'   2. Live option chain per front-month future
'   3. Live greeks + bid/ask + strike/expiry/put-call for every listed option
'
' What it does NOT get:
'   - A historical greeks time series. Bloomberg computes greeks live.
'     For the backtest, source Databento GLBX or rebuild greeks via Black-76.
'
' Usage: run BuildDataset. Output written to dedicated sheets.
'
' Nicholas Hong | Built for educational and research purposes. Not financial advice.
'================================================================
Option Explicit

'--- Config -----------------------------------------------------
Private Const TIMEOUT_SEC As Single = 90      ' max wait per request block
Private Const HIST_START  As String = "20180101"
Private Const HIST_END    As String = ""      ' "" = today
Private Const SCRATCH_NAME As String = "_bbg_scratch"

' Generic CME front-month roots. VERIFY the yellow key on your Terminal:
' CME FX futures are usually "Curncy"; some setups list options under "Comdty".
Private Function MajorRoots() As Variant
    MajorRoots = Array( _
        "EC1 Curncy", _
        "BP1 Curncy", _
        "JY1 Curncy", _
        "CD1 Curncy", _
        "AD1 Curncy", _
        "SF1 Curncy")
End Function

'================================================================
' ORCHESTRATOR
'================================================================
Public Sub BuildDataset()
    Dim t0 As Single: t0 = Timer
    Application.ScreenUpdating = False
    Application.DisplayAlerts = False

    Dim roots As Variant: roots = MajorRoots()
    Dim i As Long

    '--- 1. Futures price history -------------------------------
    For i = LBound(roots) To UBound(roots)
        Dim hist As Variant
        hist = FetchHistory(CStr(roots(i)), _
                            "PX_LAST,PX_SETTLE,PX_VOLUME,OPEN_INT", _
                            HIST_START, IIf(HIST_END = "", "", HIST_END))
        DumpBlock SheetFor("HIST_" & RootTag(CStr(roots(i)))), hist
    Next i

    '--- 2. Option chains + 3. live greeks ----------------------
    Dim greekFields As String
    greekFields = "SECURITY_DES,OPT_PUT_CALL,OPT_STRIKE_PX,OPT_EXPIRE_DT," & _
                  "PX_BID,PX_ASK,PX_LAST,IVOL_MID,DELTA_MID,GAMMA_MID," & _
                  "VEGA_MID,THETA_MID,OPEN_INT,VOLUME"

    Dim chainAll As Object: Set chainAll = CreateObject("Scripting.Dictionary")
    For i = LBound(roots) To UBound(roots)
        Dim chain As Variant
        chain = FetchChain(CStr(roots(i)))           ' column of option tickers
        Dim tickers As Variant
        tickers = FlattenColumn(chain)
        DumpBlock SheetFor("CHAIN_" & RootTag(CStr(roots(i)))), chain

        Dim greeks As Variant
        greeks = FetchReference(tickers, Split(greekFields, ","))
        DumpBlockWithHeader SheetFor("GREEKS_" & RootTag(CStr(roots(i)))), _
                            tickers, Split(greekFields, ","), greeks
    Next i

    CleanupScratch
    Application.ScreenUpdating = True
    Application.DisplayAlerts = True
    MsgBox "Done in " & Format(Timer - t0, "0.0") & "s." & vbCrLf & _
           "Check DLMT <GO> if any cells show limit errors.", vbInformation
End Sub

'================================================================
' FETCH: HISTORY (BDH)
'================================================================
Public Function FetchHistory(security As String, fields As String, _
                             startDate As String, endDate As String) As Variant
    Dim ws As Worksheet: Set ws = Scratch()
    ws.Cells.Clear
    Dim f As String
    f = "=BDH(""" & security & """,""" & fields & """,""" & startDate & """"
    If Len(endDate) > 0 Then f = f & ",""" & endDate & """" Else f = f & ","""""
    f = f & ",""Dir=V"",""Dts=S"",""Sort=A"")"
    ws.Range("A1").Formula = f
    WaitForData ws
    FetchHistory = ReadRegion(ws.Range("A1"))
End Function

'================================================================
' FETCH: OPTION CHAIN (BDS OPT_CHAIN)
'================================================================
Public Function FetchChain(underlying As String) As Variant
    Dim ws As Worksheet: Set ws = Scratch()
    ws.Cells.Clear
    ws.Range("A1").Formula = "=BDS(""" & underlying & """,""OPT_CHAIN"")"
    WaitForData ws
    FetchChain = ReadRegion(ws.Range("A1"))
End Function

'================================================================
' FETCH: REFERENCE GRID (BDP) - rows = securities, cols = fields
'================================================================
Public Function FetchReference(securities As Variant, fields As Variant) As Variant
    Dim ws As Worksheet: Set ws = Scratch()
    ws.Cells.Clear
    Dim r As Long, c As Long
    Dim nS As Long: nS = UBoundSafe(securities)
    Dim nF As Long: nF = UBoundSafe(fields)
    If nS = 0 Or nF = 0 Then Exit Function

    For r = 1 To nS
        For c = 1 To nF
            ws.Cells(r, c).Formula = _
                "=BDP(""" & CStr(securities(r - 1)) & """,""" & _
                Trim(CStr(fields(c - 1))) & """)"
        Next c
    Next r
    WaitForData ws

    Dim out() As Variant
    ReDim out(1 To nS, 1 To nF)
    For r = 1 To nS
        For c = 1 To nF
            out(r, c) = ws.Cells(r, c).Value
        Next c
    Next r
    FetchReference = out
End Function

'================================================================
' ASYNC WAIT - poll until Bloomberg RTD queries resolve
'================================================================
Private Sub WaitForData(ws As Worksheet)
    Dim t As Single: t = Timer
    Do
        DoEvents
        On Error Resume Next
        Application.CalculateUntilAsyncQueriesDone   ' resolves Bloomberg RTD
        On Error GoTo 0
        If Not IsRequesting(ws) Then Exit Do
    Loop While (Timer - t) < TIMEOUT_SEC
    If IsRequesting(ws) Then
        Debug.Print "WaitForData timed out after " & TIMEOUT_SEC & "s on " & ws.Name
    End If
End Sub

Private Function IsRequesting(ws As Worksheet) As Boolean
    Dim c As Range
    If ws.UsedRange.Cells.CountLarge = 0 Then Exit Function
    For Each c In ws.UsedRange
        If VarType(c.Value) = vbString Then
            If InStr(1, c.Value, "Requesting Data", vbTextCompare) > 0 Then
                IsRequesting = True: Exit Function
            End If
        End If
    Next c
End Function

'================================================================
' HELPERS
'================================================================
Private Function Scratch() As Worksheet
    Dim ws As Worksheet
    On Error Resume Next
    Set ws = ThisWorkbook.Worksheets(SCRATCH_NAME)
    On Error GoTo 0
    If ws Is Nothing Then
        Set ws = ThisWorkbook.Worksheets.Add
        ws.Name = SCRATCH_NAME
        ws.Visible = xlSheetVeryHidden
    End If
    Set Scratch = ws
End Function

Private Sub CleanupScratch()
    On Error Resume Next
    ThisWorkbook.Worksheets(SCRATCH_NAME).Cells.Clear
    On Error GoTo 0
End Sub

Private Function SheetFor(name As String) As Worksheet
    Dim ws As Worksheet
    On Error Resume Next
    Set ws = ThisWorkbook.Worksheets(name)
    On Error GoTo 0
    If ws Is Nothing Then
        Set ws = ThisWorkbook.Worksheets.Add(After:=ThisWorkbook.Sheets(ThisWorkbook.Sheets.Count))
        ws.Name = name
    Else
        ws.Cells.Clear
    End If
    Set SheetFor = ws
End Function

' Reads a contiguous Bloomberg output block anchored top-left.
Private Function ReadRegion(anchor As Range) As Variant
    Dim rng As Range
    Set rng = anchor.CurrentRegion
    If rng.Cells.CountLarge = 1 Then
        Dim single1(1 To 1, 1 To 1) As Variant
        single1(1, 1) = anchor.Value
        ReadRegion = single1
    Else
        ReadRegion = rng.Value
    End If
End Function

Private Sub DumpBlock(ws As Worksheet, data As Variant)
    If IsEmpty(data) Then Exit Sub
    Dim r As Long, c As Long
    r = UBound(data, 1) - LBound(data, 1) + 1
    c = UBound(data, 2) - LBound(data, 2) + 1
    ws.Range("A1").Resize(r, c).Value = data
    ws.Rows(1).Font.Bold = True
End Sub

Private Sub DumpBlockWithHeader(ws As Worksheet, ids As Variant, _
                                fields As Variant, data As Variant)
    ws.Range("A1").Value = "TICKER"
    Dim c As Long
    For c = LBound(fields) To UBound(fields)
        ws.Cells(1, 2 + c - LBound(fields)).Value = Trim(CStr(fields(c)))
    Next c
    Dim r As Long
    For r = LBound(ids) To UBound(ids)
        ws.Cells(2 + r - LBound(ids), 1).Value = CStr(ids(r))
    Next r
    If Not IsEmpty(data) Then
        ws.Range("B2").Resize(UBound(data, 1), UBound(data, 2)).Value = data
    End If
    ws.Rows(1).Font.Bold = True
    ws.Columns.AutoFit
End Sub

' Flatten a single-column 2D variant into a 0-based 1D array of tickers.
Private Function FlattenColumn(block As Variant) As Variant
    Dim out() As String
    Dim n As Long, i As Long
    n = UBound(block, 1) - LBound(block, 1) + 1
    ReDim out(0 To n - 1)
    Dim k As Long: k = 0
    For i = LBound(block, 1) To UBound(block, 1)
        If Len(Trim(CStr(block(i, LBound(block, 2))))) > 0 Then
            out(k) = CStr(block(i, LBound(block, 2)))
            k = k + 1
        End If
    Next i
    If k = 0 Then
        FlattenColumn = Array()
    Else
        ReDim Preserve out(0 To k - 1)
        FlattenColumn = out
    End If
End Function

Private Function RootTag(security As String) As String
    RootTag = Split(security, " ")(0)
End Function

Private Function UBoundSafe(v As Variant) As Long
    On Error Resume Next
    UBoundSafe = UBound(v) - LBound(v) + 1
    On Error GoTo 0
End Function
