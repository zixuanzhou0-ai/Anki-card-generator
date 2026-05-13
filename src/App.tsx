import { AppShell } from './app/AppShell'
import { useAppController } from './app/useAppController'

function App() {
  const controller = useAppController()

  return <AppShell controller={controller} />
}

export default App
