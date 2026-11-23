import Lean

unsafe def main : IO Unit := do
  Lean.enableInitializersExecution
  let env ← Lean.importModules #[{ module := `Init }] {} (loadExts := true)
  let stdout ← IO.getStdout
  stdout.putStr <| String.intercalate "\n" (Lean.Parser.getTokenTable env).values.toList
