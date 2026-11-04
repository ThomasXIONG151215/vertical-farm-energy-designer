# 操作加速：改成txt文件读取+txt文件写入
from scipy.interpolate import CubicSpline
import numpy as np
from scipy.ndimage import gaussian_filter1d
import statsmodels.api as sm

'''
1. 移动平均法 (Moving Average)
移动平均法是最简单的平滑方法，通过取当前值与其前后若干个值的平均值来平滑数据。常见的有简单移动平均（SMA）和加权移动平均（WMA）。
简单移动平均：取连续若干天（例如3天、5天等）的光照时长的平均值。
加权移动平均：给予中心点更大的权重，周围的点权重较小。

优点：实现简单，效果直观。
缺点：对于较大的波动，可能无法有效平滑。
'''
def moving_average(data, window_size=3):
    smoothed_data = []
    for i in range(len(data)):
        start = max(0, i - window_size // 2)
        end = min(len(data), i + window_size // 2 + 1)
        smoothed_data.append(np.mean(data[start:end]))
    return smoothed_data


'''
2. 指数加权移动平均 (Exponentially Weighted Moving Average, EWMA)
与普通的移动平均法不同，EWMA给最近的数据点更高的权重，权重随着时间的推移指数衰减。这样可以在平滑的同时，保留更多的短期趋势。

优点：能更好地保留数据中的趋势信息。
缺点：需要选择适当的平滑因子。
'''
def ewma(data, alpha=0.1):
    smoothed_data = [data[0]]  # 初始值
    for i in range(1, len(data)):
        smoothed_data.append(alpha * data[i] + (1 - alpha) * smoothed_data[i-1])
    return smoothed_data


'''
3. 高斯平滑 (Gaussian Smoothing)
高斯平滑是一种常用的平滑技术，它基于高斯分布的加权平均。通过高斯核函数为每个数据点赋予不同的权重，可以平滑数据并减少噪声。
高斯滤波（Gaussian filter）是基于卷积操作，使用高斯分布作为卷积核对数据进行平滑处理。

优点：能够较好地处理各种波动，尤其对于有噪声的数据。
缺点：需要设置适当的标准差，过小的标准差可能效果不明显，过大的标准差可能会过度平滑。
'''
def gaussian_smooth(data, sigma=2):
    return gaussian_filter1d(data, sigma=sigma)


'''
4. Spline 插值法 (Spline Interpolation)
插值方法通过构造一个平滑的函数（如样条函数）来近似原始数据。这种方法特别适用于需要平滑且连续的数据，如连续时间序列。
常见的插值方法包括样条插值（Cubic Spline Interpolation），可以通过拟合一条平滑的曲线来平滑数据。

优点：适用于需要精确拟合的连续数据，平滑效果较好。
缺点：计算复杂度相对较高。
'''
def spline_smooth(data):
    x = np.arange(len(data))
    cs = CubicSpline(x, data, bc_type='natural')
    smoothed_data = cs(x)
    return smoothed_data


'''
5. 局部加权回归 (Local Weighted Regression, LOWESS)
LOWESS（也称为LOESS）是一种非参数回归方法，通过对每个数据点周围的局部数据进行加权回归来进行平滑。这种方法不假设数据的具体形式，适合处理非线性关系。

优点：适用于非线性趋势，能够灵活地调整局部平滑程度。
缺点：计算成本较高，尤其是数据量较大的时候。
'''
def lowess_smooth(data, frac=0.1):
    smoothed_data = sm.nonparametric.lowess(data, np.arange(len(data)), frac=frac)
    return smoothed_data[:, 1]

# data_str = \
# '12	12	12	12	12	12.00001	12	12	12	12.09126	12	12	12	12	12	12.11096	17.61089	12	24	12	23.77194	23.76677	23.78203	23.7521	23.75774	23.76083	24'
# data_array = np.array([float(x) for x in data_str.split('\t')])

best999 = np.array([
    12.000026766331892,12.0,12.0,12.0,12.0,12.0,12.0,12.0,12.0,12.0,12.0,12.0,12.0,12.0,12.0,12.0,12.25107119149221,12.0,24.0,17.085187474206048,23.7675388605173,23.752964381503574,23.76014614854467,24.0,23.96270967865226,23.818432621897795,24.0
], dtype=np.float64)

# 计算需要添加的值
new_value = 16 * 28 - np.sum(best999)
print('last_day\n' + str(new_value))
# 在数组末尾添加新值
best = np.append(best999, new_value)
print('best\n' + str(best))

# print('\nmoving_average\n' + str(moving_average(photoperiod)))
# print('\newma\n' + str(ewma(photoperiod)))
print('\ngaussian_smooth\n' + str(gaussian_smooth(best)))
# print('\nspline_smooth\n' + str(spline_smooth(photoperiod)))
# print('\nlowess_smooth\n' + str(lowess_smooth(photoperiod)))
