import { config } from 'md-editor-v3'
import { markdownFrontmatter } from './markdown-frontmatter'

// Shared by skill details, public/release previews and the editor's live preview.
config({ markdownItConfig: md => md.use(markdownFrontmatter) })
