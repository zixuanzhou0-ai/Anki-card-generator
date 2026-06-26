import { ExternalLink, ShieldCheck } from 'lucide-react'

import {
  APP_ANKI_DISCLAIMER,
  APP_COPYRIGHT,
  APP_DISPLAY_NAME,
  APP_GITHUB_URL,
  APP_NAME,
  APP_RELEASE_LABEL,
} from '../../domain/appInfo'

function GitHubMark() {
  return (
    <svg aria-hidden="true" className="about-github-mark" viewBox="0 0 24 24" focusable="false">
      <path
        fill="currentColor"
        d="M12 2a10 10 0 0 0-3.16 19.49c.5.09.68-.22.68-.48v-1.7c-2.78.61-3.37-1.19-3.37-1.19-.45-1.15-1.11-1.46-1.11-1.46-.91-.62.07-.61.07-.61 1 .07 1.53 1.03 1.53 1.03.9 1.53 2.35 1.09 2.92.83.09-.65.35-1.09.64-1.34-2.22-.25-4.56-1.11-4.56-4.94 0-1.09.39-1.98 1.03-2.68-.1-.25-.45-1.27.1-2.64 0 0 .84-.27 2.75 1.02A9.56 9.56 0 0 1 12 6c.85 0 1.7.11 2.5.33 1.91-1.29 2.75-1.02 2.75-1.02.55 1.37.2 2.39.1 2.64.64.7 1.03 1.59 1.03 2.68 0 3.84-2.34 4.69-4.57 4.94.36.31.68.92.68 1.86v2.76c0 .26.18.57.69.48A10 10 0 0 0 12 2Z"
      />
    </svg>
  )
}
export function AboutSettingsPanel() {
  const openGitHub = () => {
    window.open(APP_GITHUB_URL, '_blank', 'noopener,noreferrer')
  }

  return (
    <section className="settings-section about-settings-panel" aria-label="关于和版权">
      <div className="about-product-card">
        <div className="about-product-mark" aria-hidden="true">
          ACG
        </div>
        <div>
          <p className="eyebrow">About</p>
          <h3>{APP_DISPLAY_NAME}</h3>
          <p>{APP_NAME} 是面向 Windows 桌面端的视频到 Anki 卡片生成器，用于把本地视频、字幕或视频链接整理成可复习的 APKG 学习卡。</p>
        </div>
        <span className="about-version-pill">{APP_RELEASE_LABEL}</span>
      </div>

      <div className="about-action-row">
        <button className="secondary-button about-github-button" type="button" onClick={openGitHub}>
          <GitHubMark />
          GitHub 仓库
          <ExternalLink size={15} />
        </button>
      </div>

      <div className="about-info-grid">
        <article className="about-info-card">
          <strong>版权声明</strong>
          <p>{APP_COPYRIGHT}</p>
        </article>
        <article className="about-info-card">
          <strong>Anki 独立声明</strong>
          <p>{APP_ANKI_DISCLAIMER}</p>
        </article>
        <article className="about-info-card about-info-card-wide">
          <span className="about-info-icon" aria-hidden="true">
            <ShieldCheck size={18} />
          </span>
          <div>
            <strong>隐私与密钥边界</strong>
            <p>模型 API key 和 TTS key 只应保存在本机配置或系统凭据中；不要把密钥、测试素材、APKG、日志或缓存提交到 GitHub。</p>
          </div>
        </article>
      </div>
    </section>
  )
}