"""连线画法：散点 / 折线 / 平滑（只影响"怎么连"，一个数据点都不改）。

为什么要单独一层：文献里的 Nyquist 图通常是"实测散点 + 拟合曲线"，
而实测数据直接连折线时，相邻两点之间的走向其实没测过。三种画法的诚实度不一样：

    scatter  只画符号，不连线 —— 最保守，看到什么就是什么
    segment  相邻实测点直连（默认）—— 每段以两点间直线近似，段内仍是"没测"
    smooth   过实测点的单调三次 Hermite 插值（PCHIP）—— 好看，但中间点同样是算出来的

所以 smooth 只是"好看"，导出留痕里必须写清楚它是插值、不是实测。
scipy 没装，PCHIP 自己实现（Fritsch–Carlson 保单调，不会在两点之间凭空鼓出峰谷）。
"""

CONNECT_MODES = ("scatter", "segment", "smooth")
CONNECT_LABEL = {"scatter": "散点", "segment": "折线", "smooth": "平滑"}
CONNECT_NOTE = {
    "scatter": "只画实测符号，不连线",
    "segment": "相邻实测点直连（段内为两点间直线近似）",
    "smooth": "过实测点的 PCHIP 平滑插值（中间点为插值算出，非实测）",
}


def _end_slope(h0: float, h1: float, d0: float, d1: float) -> float:
    """端点导数：三点公式 + 保形限制，避免端点外冲。"""
    m = ((2.0 * h0 + h1) * d0 - h0 * d1) / (h0 + h1)
    if m * d0 <= 0:
        return 0.0
    if d0 * d1 < 0 and abs(m) > abs(3.0 * d0):
        return 3.0 * d0
    return m


def _slopes(h, delta):
    """内部节点取加权调和平均：异号或为 0 时导数置 0（保单调，不制造假峰）。"""
    n = len(delta) + 1
    m = [0.0] * n
    if n == 2:
        m[0] = m[1] = delta[0]
        return m
    for i in range(1, n - 1):
        d0, d1 = delta[i - 1], delta[i]
        if d0 == 0 or d1 == 0 or (d0 > 0) != (d1 > 0):
            m[i] = 0.0
        else:
            w1 = 2.0 * h[i] + h[i - 1]
            w2 = h[i] + 2.0 * h[i - 1]
            m[i] = (w1 + w2) / (w1 / d0 + w2 / d1)
    m[0] = _end_slope(h[0], h[1], delta[0], delta[1])
    m[-1] = _end_slope(h[-1], h[-2], delta[-1], delta[-2])
    return m


def _sample(ys, h, m, per):
    """按 Hermite 基函数在每段内采样（每段 per 个点，末端补齐）。"""
    res = []
    for i in range(len(ys) - 1):
        step = h[i]
        for k in range(per):
            u = k / per
            u2, u3 = u * u, u * u * u
            res.append(((2 * u3 - 3 * u2 + 1) * ys[i] +
                        (u3 - 2 * u2 + u) * step * m[i] +
                        (-2 * u3 + 3 * u2) * ys[i + 1] +
                        (u3 - u2) * step * m[i + 1]))
    res.append(ys[-1])
    return res


def smooth_path(xy, per_gap: int = 10, max_pts: int = 1600):
    """把点序列插值成平滑路径，返回 [(x, y), ...]。

    参数化用点序 t = 0,1,2,...：Nyquist 曲线在感抗尾巴上 Z' 会回折，
    按横坐标排序插值会把回折处压平；按点序（即频率序）走就不会。
    x、y 各自独立做 PCHIP，因此不要求 x 单调。

    少于 3 点没有平滑可言，原样返回（2 点就是直线段）。
    """
    pts = [(float(p[0]), float(p[1])) for p in xy]
    n = len(pts)
    if n < 3:
        return pts
    # 总顶点数控制在 max_pts 内；至少每段 4 个才看得出弧度
    per = max(4, min(int(per_gap), max(4, max_pts // max(1, n - 1))))
    h = [1.0] * (n - 1)              # t = 0,1,2,... 等间距
    comps = []
    for axis in (0, 1):
        ys = [p[axis] for p in pts]
        delta = [ys[i + 1] - ys[i] for i in range(n - 1)]
        comps.append(_sample(ys, h, _slopes(h, delta), per))
    return list(zip(comps[0], comps[1]))
