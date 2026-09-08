/**
 * 企业认知来源端口。
 *
 * 认知编译器只依赖这个中立接口，不直接知道工作台 runtime-state、页面或飞书。
 * 当前实现仍然由工作台后端提供 adapter；未来迁移存储时只替换 adapter。
 */

export const COGNITION_SOURCE_PORT_VERSION = 'cognition-source-port-v1';

export function createCognitionSourcePort({
  catalog,
  profile,
  readState,
  revisions = {},
} = {}) {
  const stateReader = typeof readState === 'function' ? readState : () => ({ data: {}, revision: 0, updatedAt: '' });
  return Object.freeze({
    version: COGNITION_SOURCE_PORT_VERSION,
    catalog: catalog && typeof catalog === 'object' ? catalog : {},
    profile: profile && typeof profile === 'object' ? profile : {},
    readState: kind => stateReader(kind) || { data: {}, revision: 0, updatedAt: '' },
    revisions: { ...revisions },
  });
}

export function assertCognitionSourcePort(source) {
  if (!source || source.version !== COGNITION_SOURCE_PORT_VERSION || typeof source.readState !== 'function') {
    throw new Error('无效的企业认知来源端口');
  }
  return source;
}
