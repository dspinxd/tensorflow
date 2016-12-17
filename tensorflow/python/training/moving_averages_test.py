# Copyright 2015 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Functional test for moving_averages.py."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from tensorflow.python.framework import constant_op
from tensorflow.python.framework import dtypes
from tensorflow.python.framework import ops
from tensorflow.python.ops import array_ops
from tensorflow.python.ops import gen_state_ops
from tensorflow.python.ops import variable_scope
from tensorflow.python.ops import variables
from tensorflow.python.platform import test
from tensorflow.python.training import moving_averages


class MovingAveragesTest(test.TestCase):

  def testAssignMovingAverageWithoutZeroDebias(self):
    with self.test_session():
      var = variables.Variable([10.0, 11.0])
      val = constant_op.constant([1.0, 2.0], dtypes.float32)
      decay = 0.25
      assign = moving_averages.assign_moving_average(
          var, val, decay, zero_debias=False)
      variables.global_variables_initializer().run()
      self.assertAllClose([10.0, 11.0], var.eval())
      assign.op.run()
      self.assertAllClose(
          [10.0 * 0.25 + 1.0 * (1.0 - 0.25), 11.0 * 0.25 + 2.0 * (1.0 - 0.25)],
          var.eval())

  def testAssignMovingAverage(self):
    with self.test_session():
      var = variables.Variable([0.0, 0.0])
      val = constant_op.constant([1.0, 2.0], dtypes.float32)
      decay = 0.25
      assign = moving_averages.assign_moving_average(var, val, decay)
      variables.global_variables_initializer().run()
      self.assertAllClose([0.0, 0.0], var.eval())
      assign.op.run()
      self.assertAllClose([
          1.0 * (1.0 - 0.25) / (1 - 0.25**2), 2.0 * (1.0 - 0.25) / (1 - 0.25**2)
      ], var.eval())

  def testWeightedMovingAverage(self):
    with self.test_session() as sess:
      decay = 0.5
      weight = array_ops.placeholder(dtypes.float32, [])
      val = array_ops.placeholder(dtypes.float32, [])

      wma = moving_averages.weighted_moving_average(val, decay, weight)
      variables.global_variables_initializer().run()

      # Get the first weighted moving average.
      val_1 = 3.0
      weight_1 = 4.0
      wma_array = sess.run(wma, feed_dict={val: val_1, weight: weight_1})
      numerator_1 = val_1 * weight_1 * (1.0 - decay)
      denominator_1 = weight_1 * (1.0 - decay)
      self.assertAllClose(numerator_1 / denominator_1, wma_array)

      # Get the second weighted moving average.
      val_2 = 11.0
      weight_2 = 22.0
      wma_array = sess.run(wma, feed_dict={val: val_2, weight: weight_2})
      numerator_2 = numerator_1 * decay + val_2 * weight_2 * (1.0 - decay)
      denominator_2 = denominator_1 * decay + weight_2 * (1.0 - decay)
      self.assertAllClose(numerator_2 / denominator_2, wma_array)


def _Repeat(value, dim):
  if dim == 1:
    return value
  return [value] * dim


class ExponentialMovingAverageTest(test.TestCase):

  def _CheckDecay(self, ema, actual_decay, dim):

    def _Scale(dk, steps):
      if ema._zero_debias:
        return 1 - dk**(steps + 1)
      else:
        return 1

    tens = _Repeat(10.0, dim)
    thirties = _Repeat(30.0, dim)
    var0 = variables.Variable(tens, name="v0")
    var1 = variables.Variable(thirties, name="v1")
    variables.global_variables_initializer().run()
    # Note that tensor2 is not a Variable but just a plain Tensor resulting
    # from the sum operation.
    tensor2 = var0 + var1
    update = ema.apply([var0, var1, tensor2])
    avg0 = ema.average(var0)
    avg1 = ema.average(var1)
    avg2 = ema.average(tensor2)

    self.assertItemsEqual([var0, var1], variables.moving_average_variables())

    self.assertFalse(avg0 in variables.trainable_variables())
    self.assertFalse(avg1 in variables.trainable_variables())
    self.assertFalse(avg2 in variables.trainable_variables())
    variables.global_variables_initializer().run()

    self.assertEqual("v0/ExponentialMovingAverage:0", avg0.name)
    self.assertEqual("v1/ExponentialMovingAverage:0", avg1.name)
    self.assertEqual("add/ExponentialMovingAverage:0", avg2.name)

    # Check initial values.
    self.assertAllClose(tens, var0.eval())
    self.assertAllClose(thirties, var1.eval())
    self.assertAllClose(_Repeat(10.0 + 30.0, dim), tensor2.eval())

    # Check that averages are initialized correctly.
    self.assertAllClose(tens, avg0.eval())
    self.assertAllClose(thirties, avg1.eval())
    # Note that averages of Tensor's initialize to zeros_like since no value
    # of the Tensor is known because the Op has not been run (yet).
    self.assertAllClose(_Repeat(0.0, dim), avg2.eval())

    # Update the averages and check.
    update.run()
    dk = actual_decay

    expected = _Repeat(10.0 * dk + 10.0 * (1 - dk), dim)
    self.assertAllClose(expected, avg0.eval())
    expected = _Repeat(30.0 * dk + 30.0 * (1 - dk), dim)
    self.assertAllClose(expected, avg1.eval())
    expected = _Repeat(0.0 * dk + (10.0 + 30.0) * (1 - dk) / _Scale(dk, 1), dim)
    self.assertAllClose(expected, avg2.eval())

    # Again, update the averages and check.
    update.run()
    expected = _Repeat((10.0 * dk + 10.0 * (1 - dk)) * dk + 10.0 * (1 - dk),
                       dim)
    self.assertAllClose(expected, avg0.eval())
    expected = _Repeat((30.0 * dk + 30.0 * (1 - dk)) * dk + 30.0 * (1 - dk),
                       dim)
    self.assertAllClose(expected, avg1.eval())
    expected = _Repeat(((0.0 * dk + (10.0 + 30.0) * (1 - dk)) * dk +
                        (10.0 + 30.0) * (1 - dk)) / _Scale(dk, 2), dim)
    self.assertAllClose(expected, avg2.eval())

  def testAverageVariablesNoNumUpdates_Scalar(self):
    with self.test_session():
      ema = moving_averages.ExponentialMovingAverage(0.25)
      self._CheckDecay(ema, actual_decay=0.25, dim=1)

  def testAverageVariablesNoNumUpdates_Scalar_Debias(self):
    with self.test_session():
      ema = moving_averages.ExponentialMovingAverage(0.25, zero_debias=True)
      self._CheckDecay(ema, actual_decay=0.25, dim=1)

  def testAverageVariablesNoNumUpdates_Vector(self):
    with self.test_session():
      ema = moving_averages.ExponentialMovingAverage(0.25)
      self._CheckDecay(ema, actual_decay=0.25, dim=5)

  def testAverageVariablesNoNumUpdates_Vector_Debias(self):
    with self.test_session():
      ema = moving_averages.ExponentialMovingAverage(0.25, zero_debias=True)
      self._CheckDecay(ema, actual_decay=0.25, dim=5)

  def testAverageVariablesNumUpdates_Scalar(self):
    with self.test_session():
      # With num_updates 1, the decay applied is 0.1818
      ema = moving_averages.ExponentialMovingAverage(0.25, num_updates=1)
      self._CheckDecay(ema, actual_decay=0.181818, dim=1)

  def testAverageVariablesNumUpdates_Scalar_Debias(self):
    with self.test_session():
      # With num_updates 1, the decay applied is 0.1818
      ema = moving_averages.ExponentialMovingAverage(
          0.25, num_updates=1, zero_debias=True)
      self._CheckDecay(ema, actual_decay=0.181818, dim=1)

  def testAverageVariablesNumUpdates_Vector(self):
    with self.test_session():
      # With num_updates 1, the decay applied is 0.1818
      ema = moving_averages.ExponentialMovingAverage(0.25, num_updates=1)
      self._CheckDecay(ema, actual_decay=0.181818, dim=5)

  def testAverageVariablesNumUpdates_Vector_Debias(self):
    with self.test_session():
      # With num_updates 1, the decay applied is 0.1818
      ema = moving_averages.ExponentialMovingAverage(
          0.25, num_updates=1, zero_debias=True)
      self._CheckDecay(ema, actual_decay=0.181818, dim=5)

  def testAverageVariablesWithControlDeps(self):
    with self.test_session() as sess:
      v0 = variables.Variable(0, name="v0")
      add_to_v0 = v0.assign_add(1)
      v1 = variables.Variable([10.0], name="v1")
      assign_to_v1 = v1.assign([20.0])
      ema = moving_averages.ExponentialMovingAverage(0.25)
      with ops.control_dependencies([add_to_v0]):
        ema_op = ema.apply([v1])
      # the moving average of v1 should not have any control inputs
      v1_avg = ema.average(v1)
      self.assertEqual([], v1_avg.initializer.control_inputs)
      self.assertEqual([], v1_avg.value().op.control_inputs)
      self.assertEqual([], v1_avg.value().op.control_inputs)
      # We should be able to initialize v1_avg before v0.
      sess.run(v1_avg.initializer)
      sess.run(v0.initializer)
      self.assertEqual([10.0], sess.run(v1_avg))
      # running ema_op should add to v0 (in addition to updating v1_avg)
      sess.run(assign_to_v1)
      sess.run(ema_op)
      self.assertEqual(1, sess.run(v0))
      self.assertEqual([17.5], sess.run(v1_avg))

  def averageVariablesNamesHelper(self, zero_debias):
    with self.test_session():
      v0 = variables.Variable(10.0, name="v0")
      v1 = variables.Variable(30.0, name="v1")
      # Add a non-trainable variable.
      v2 = variables.Variable(20.0, name="v2", trainable=False)
      tensor2 = v0 + v1
      ema = moving_averages.ExponentialMovingAverage(
          0.25, zero_debias=zero_debias, name="foo")
      self.assertEqual("v0/foo", ema.average_name(v0))
      self.assertEqual("v1/foo", ema.average_name(v1))
      self.assertEqual("add/foo", ema.average_name(tensor2))
      ema.apply([v0, v1, tensor2])
      vars_to_restore = ema.variables_to_restore()
      # vars_to_restore should contain the following:
      # {v0/foo : v0,
      #  v1/foo : v1,
      #  add/foo : add/foo,
      #  v2 : v2}
      expected_names = [
          ema.average_name(v0), ema.average_name(v1), ema.average_name(tensor2),
          v2.op.name
      ]
      if zero_debias:
        # vars_to_restore should also contain the following:
        #  {add/foo/biased: add/foo/biased,
        #  add/foo/local_step: add/foo/local_step}
        expected_names += [
            ema.average_name(tensor2) + "/biased",
            ema.average_name(tensor2) + "/local_step"
        ]
      self.assertEqual(sorted(vars_to_restore.keys()), sorted(expected_names))
      self.assertEqual(ema.average_name(v0), ema.average(v0).op.name)
      self.assertEqual(ema.average_name(v1), ema.average(v1).op.name)
      self.assertEqual(ema.average_name(tensor2), ema.average(tensor2).op.name)

  def testAverageVariablesNames(self):
    self.averageVariablesNamesHelper(zero_debias=True)

  def testAverageVariablesNamesNoDebias(self):
    self.averageVariablesNamesHelper(zero_debias=False)

  def averageVariablesNamesRespectScopeHelper(self, zero_debias):
    # See discussion on #2740.
    with self.test_session():
      with variable_scope.variable_scope("scope1"):
        v0 = variables.Variable(10.0, name="v0")
        v1 = variables.Variable(30.0, name="v1")
        # Add a non-trainable variable.
        v2 = variables.Variable(20.0, name="v2", trainable=False)
        tensor2 = v0 + v1
      with variable_scope.variable_scope("scope2"):
        ema = moving_averages.ExponentialMovingAverage(
            0.25, zero_debias=zero_debias, name="foo")
        self.assertEqual("scope2/scope1/v0/foo", ema.average_name(v0))
        self.assertEqual("scope2/scope1/v1/foo", ema.average_name(v1))
        self.assertEqual("scope2/scope1/add/foo", ema.average_name(tensor2))
        ema.apply([v0, v1, tensor2])
        vars_to_restore = ema.variables_to_restore()
        # vars_to_restore should contain the following:
        # {scope2/scope1/v0/foo : v0,
        #  scope2/scope1/v1/foo : v1,
        #  scope2/scope1/add/foo : add/foo,
        #  scope1/v2 : v2}
        expected_names = [
            ema.average_name(v0), ema.average_name(v1),
            ema.average_name(tensor2), v2.op.name
        ]
        if zero_debias:
          # vars_to_restore should also contain the following:
          # {scope2/scope2/scope1/add/foo/biased: add/foo/biased,
          #  scope2/scope2/scope1/add/foo/local_step: add/foo/local_step}
          sc = "scope2/"
          expected_names += [
              sc + ema.average_name(tensor2) + "/biased",
              sc + ema.average_name(tensor2) + "/local_step"
          ]

        self.assertEqual(sorted(vars_to_restore.keys()), sorted(expected_names))
        self.assertEqual(ema.average_name(v0), ema.average(v0).op.name)
        self.assertEqual(ema.average_name(v1), ema.average(v1).op.name)
        self.assertEqual(
            ema.average_name(tensor2), ema.average(tensor2).op.name)

  def testAverageVariablesNamesRespectScope(self):
    self.averageVariablesNamesRespectScopeHelper(zero_debias=True)

  def testAverageVariablesNamesRespectScopeNoDebias(self):
    self.averageVariablesNamesRespectScopeHelper(zero_debias=False)

  def testSubsetAverageVariablesNames(self):
    with self.test_session():
      v0 = variables.Variable(10.0, name="v0")
      v1 = variables.Variable(30.0, name="v1")
      # Add a non-trainable variable.
      v2 = variables.Variable(20.0, name="v2", trainable=False)
      tensor2 = v0 + v1
      ema = moving_averages.ExponentialMovingAverage(0.25, name="foo_avg")
      self.assertEqual("v0/foo_avg", ema.average_name(v0))
      self.assertEqual("v1/foo_avg", ema.average_name(v1))
      self.assertEqual("add/foo_avg", ema.average_name(tensor2))
      vars_to_restore = ema.variables_to_restore([v0, tensor2])
      # vars_to_restore should contain the following:
      # {v0/foo_avg : v0,
      #  add/foo_avg : add
      #  v1 : v1,
      #  v2 : v2}
      self.assertEqual(
          sorted(vars_to_restore.keys()),
          sorted([
              ema.average_name(v0), ema.average_name(tensor2), v1.op.name,
              v2.op.name
          ]))
      ema.apply([v0, v1, tensor2])
      self.assertEqual(ema.average_name(v0), ema.average(v0).op.name)
      self.assertEqual(ema.average_name(v1), ema.average(v1).op.name)
      self.assertEqual(ema.average_name(tensor2), ema.average(tensor2).op.name)

  def testAverageVariablesDeviceAssignment(self):
    with ops.device("/job:dev_v0"):
      v0 = variables.Variable(10.0, name="v0")
    with ops.device("/job:dev_v1"):
      v1 = gen_state_ops._variable(
          shape=[1],
          dtype=dtypes.float32,
          name="v1",
          container="",
          shared_name="")
      v1.set_shape([1])
    tensor2 = v0 + v1
    ema = moving_averages.ExponentialMovingAverage(0.25, name="foo_avg")
    with ops.device("/job:default"):
      ema.apply([v0, v1, tensor2])
    self.assertDeviceEqual("/job:dev_v0", ema.average(v0).device)
    self.assertDeviceEqual("/job:dev_v1", ema.average(v1).device)
    # However, the colocation property is maintained.
    self.assertEqual([b"loc:@v1"], ema.average(v1).op.colocation_groups())
    self.assertDeviceEqual("/job:default", ema.average(tensor2).device)


if __name__ == "__main__":
  test.main()
