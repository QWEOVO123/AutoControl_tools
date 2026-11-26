import { defineStore } from 'pinia'
import { ref } from 'vue'

const KEY = 'agent-studio.background.v1'
function savedBackground() {
  try {
    const saved = localStorage.getItem(KEY)
    return saved && /^data:image\/jpeg;base64,[A-Za-z0-9+/=]+$/.test(saved) ? saved : ''
  } catch {
    return ''
  }
}

export const useAppearance = defineStore('appearance', () => {
  const background = ref(savedBackground())

  async function setBackground(file: File) {
    if (
      !['image/jpeg', 'image/png', 'image/webp'].includes(file.type) ||
      file.size > 16 * 1024 * 1024
    ) {
      throw new Error('请选择 16 MiB 以内的 JPEG、PNG 或 WebP 图片。')
    }
    const image = await createImageBitmap(file)
    try {
      const scale = Math.min(1, 1920 / Math.max(image.width, image.height))
      const canvas = document.createElement('canvas')
      canvas.width = Math.max(1, Math.round(image.width * scale))
      canvas.height = Math.max(1, Math.round(image.height * scale))
      const context = canvas.getContext('2d')
      if (!context) throw new Error('当前浏览器无法处理背景图片。')
      context.fillStyle = '#102022'
      context.fillRect(0, 0, canvas.width, canvas.height)
      context.drawImage(image, 0, 0, canvas.width, canvas.height)
      const data = canvas.toDataURL('image/jpeg', 0.8)
      try {
        localStorage.setItem(KEY, data)
      } catch {
        throw new Error('浏览器无法保存这张图片，请换一张较小的图片。')
      }
      background.value = data
    } finally {
      image.close()
    }
  }

  function reset() {
    localStorage.removeItem(KEY)
    background.value = ''
  }

  return { background, setBackground, reset }
})
