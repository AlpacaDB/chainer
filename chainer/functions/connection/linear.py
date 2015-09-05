import math

import numpy

from chainer import cuda
from chainer import function
from chainer import model
from chainer.utils import type_check


def _as_mat(x):
    if x.ndim == 2:
        return x
    return x.reshape(len(x), -1)


class Linear(model.Model, function.Function):

    """Linear function (a.k.a. fully-connected layer or affine transformation).

    This function holds a weight matrix ``W`` and a bias vector ``b``.

    The weight matrix ``W`` has shape ``(out_size, in_size)``.
    This matrix is initialized with i.i.d. Gaussian samples, each of which has
    zero mean and deviation :math:`\sqrt{1/\\text{in_size}}`.
    The deviation is scaled by factor ``wscale`` if specified.

    The bias vector ``b`` is of size ``out_size``.
    Each element is initialized with the ``bias`` value.
    If ``nobias`` argument is set to True, then this function does not hold a
    bias vector.

    Let :math:`X` be an input matrix, and :math:`W, b` the weight matrix and
    the bias vector, respectively.
    Then, the output matrix :math:`Y` is computed by :math:`Y = XW^\\top + b`,
    where the addition by :math:`b` is broadcasted across the minibatch.

    Args:
        in_size (int): Dimension of input vectors.
        out_size (int): Dimension of output vectors.
        wscale (float): Scaling factor of the weight matrix.
        bias (float): Initial bias value.
        nobias (bool): If True, then this function does not use the bias.
        initialW (2-D array): Initial weight value. If ``None``, then this
            function uses to initialize ``wscale``.
        initial_bias (1-D array): Initial bias value. If ``None``, then this
            function uses to initialize ``bias``.

    .. note::

       This function accepts an input variable of a non-matrix array.
       In this case, the leading dimension is treated as the batch dimension,
       and the other dimensions are reduced to one dimension.

    """
    def __init__(self, in_size, out_size, wscale=1, bias=0, nobias=False,
                 initialW=None, initial_bias=None):
        super(Linear, self).__init__()
        if initialW is not None:
            assert initialW.shape == (out_size, in_size)
            self.params['W'] = initialW
        else:
            self.params['W'] = numpy.random.normal(
                0, wscale * math.sqrt(1. / in_size),
                (out_size, in_size)).astype(numpy.float32)

        if initial_bias is not None:
            assert initial_bias.shape == (out_size,)
            self.params['b'] = initial_bias
        elif not nobias:
            self.params['b'] = numpy.repeat(numpy.float32(bias), out_size)

    def check_type_forward(self, in_types):
        type_check.expect(in_types.size() == 1)
        x_type, = in_types

        type_check.expect(
            x_type.dtype == numpy.float32,
            x_type.ndim >= 2,
            (type_check.Variable(numpy.prod, 'prod')(x_type.shape[1:]) ==
             type_check.Variable(self.params['W'].shape[1], 'W.shape[1]')),
        )

    def forward(self, x):
        x = _as_mat(x[0])
        Wx = x.dot(self.params['W'].T)
        b = self.params.get('b', None)
        if b is not None:
            Wx += b
        return Wx,

    def backward(self, x, gy):
        _x = _as_mat(x[0])
        self.grads['W'] += gy[0].T.dot(_x)
        gb = self.grads.get('b', None)
        if gb is not None:
            gb += gy[0].sum(0)
        return gy[0].dot(self.params['W']).reshape(x[0].shape),


class NonparameterizedLinear(function.Function):

    """Nonparameterized linear class.

    .. seealso:: :class:`Linear`

    """

    def check_type_forward(self, in_types):
        type_check.expect(
            2 <= in_types.size(),
            in_types.size() <= 3,
        )
        x_type = in_types[0]
        w_type = in_types[1]

        prod = type_check.Variable(numpy.prod, 'prod')
        type_check.expect(
            x_type.dtype == numpy.float32,
            w_type.dtype == numpy.float32,
            x_type.ndim >= 2,
            w_type.ndim == 2,
            prod(x_type.shape[1:]) == w_type.shape[1],
        )
        if in_types.size().eval() == 3:
            b_type = in_types[2]
            type_check.expect(
                b_type.ndim == 1,
                b_type.shape[0] == w_type.shape[0],
            )

    def forward(self, x):
        W = x[1]
        out_size, in_size = W.shape
        if len(x) == 3:
            func = Linear(
                in_size, out_size, initialW=W, initial_bias=x[2])
        else:
            func = Linear(
                in_size, out_size, initialW=W, nobias=True)
        self.func = func
        if any(isinstance(i, cuda.ndarray) for i in x):
            func.to_gpu()
        return func.forward(x[:1])

    def backward(self, x, gy):
        func = self.func
        func.zerograds()
        gx = func.backward(x[:1], gy)
        gb = func.grads.get('b', None)
        if gb is None:
            return (gx[0], func.grads['W'])
        return (gx[0], func.grads['W'], gb)


def linear(x, W, b=None):
    """Nonparameterized linear function.

    Args:
        x (~chainer.Variable): Input variable.
        W (~chainer.Variable): Weight variable.
        b (~chainer.Variable): Bias variable (optional).

    Returns:
        ~chainer.Variable: Output variable.

    .. seealso:: :class:`Linear`

    """
    if b is None:
        return NonparameterizedLinear()(x, W)
    else:
        return NonparameterizedLinear()(x, W, b)
