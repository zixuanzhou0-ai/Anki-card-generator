import { Component, type ErrorInfo, type ReactNode } from 'react'

import { recordRendererError } from '../services/tauriWorker'

type AppErrorBoundaryProps = {
  children: ReactNode
}

type AppErrorBoundaryState = {
  error: Error | null
}

export class AppErrorBoundary extends Component<AppErrorBoundaryProps, AppErrorBoundaryState> {
  state: AppErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): AppErrorBoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    void recordRendererError({
      kind: 'react_error_boundary',
      at: new Date().toISOString(),
      error: {
        name: error.name,
        message: error.message,
        stack: error.stack,
      },
      componentStack: info.componentStack,
    }).catch(() => {
      // Best-effort crash breadcrumb.
    })
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <main className="app-crash-boundary" role="alert">
        <section>
          <span>界面保护</span>
          <h1>生成界面遇到异常，但应用没有直接退出</h1>
          <p>错误诊断已写入本地日志。请重启桌面端或返回上一步，用少量学习点重试。</p>
          <pre>{this.state.error.message}</pre>
        </section>
      </main>
    )
  }
}
