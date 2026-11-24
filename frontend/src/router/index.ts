import { createRouter, createWebHistory } from 'vue-router'

import Overview from '@/views/Overview.vue'
import RecoveryScopeView from '@/views/RecoveryScopeView.vue'
import WorkbenchView from '@/views/WorkbenchView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'overview', component: Overview },
    // 恢复范围看板有专属视图，要先于通用模块路由注册。
    { path: '/recovery_scope', name: 'recovery_scope', component: RecoveryScopeView },
    { path: '/:moduleKey', name: 'module', component: WorkbenchView, props: true },
  ],
})

export default router
