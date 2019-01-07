import numpy as np
import tensorflow as tf
from tensorflow.python.ops import tensor_array_ops, control_flow_ops


class Generator(object):
    def __init__(self, num_vocabulary, batch_size, emb_dim, hidden_dim,
                 sequence_length, start_token,
                 learning_rate=0.01, reward_gamma=0.95,
                 add_data = False):
        self.num_vocabulary = num_vocabulary
        self.batch_size = batch_size
        self.emb_dim = emb_dim
        self.hidden_dim = hidden_dim
        self.sequence_length = sequence_length
        self.start_token = tf.constant([start_token] * self.batch_size, dtype=tf.int32)
        self.learning_rate = tf.Variable(float(learning_rate), trainable=False)
        self.reward_gamma = reward_gamma
        self.g_params = []
        self.d_params = []
        self.temperature = 1.0
        self.grad_clip = 5.0
        self.ADDDATA = add_data
        if self.ADDDATA == True:
            #add class and grade params
            self.num_class = 14
            self.class_dim = 5
            self.num_grade = 90
            self.grade_dim = 5
            self.position_dim = 5
        
        self.attention_size = 16

        self.expected_reward = tf.Variable(tf.zeros([self.sequence_length]))

        with tf.variable_scope('generator'):
            #self.g_embeddings = tf.Variable(self.init_matrix([self.num_vocabulary, self.emb_dim]))
            if self.ADDDATA == True:
                self.g_embeddings = tf.Variable(self.init_matrix([self.num_vocabulary, self.emb_dim - self.class_dim - self.grade_dim - position_dim]))
                self.class_embeddings = tf.Variable(self.init_matrix([self.num_class, self.class_dim]))
                self.grade_embeddings = tf.Variable(self.init_matrix([self.num_grade, self.grade_dim]))
                self.p_embeddings = tf.Variable(self.init_matrix([self.num_grade, self.position_dim]))
                self.g_params.append(self.g_embeddings)
                self.g_params.append(self.class_embeddings)
                self.g_params.append(self.grade_embeddings)
                self.g_params.append(self.p_embeddings)

        # placeholder definition
        self.x = tf.placeholder(tf.int32, shape=[self.batch_size,
                                                 self.sequence_length])  # sequence of tokens generated by generator
        if self.ADDDATA == True:
            self.classes = tf.placeholder(tf.int32, shape=[self.batch_size,
                                                           self.sequence_length])
            self.grades = tf.placeholder(tf.int32, shape=[self.batch_size,
                                                          self.sequence_length])

        # processed for batch
        with tf.device("/cpu:0"):
            self.processed_x = tf.transpose(tf.nn.embedding_lookup(self.g_embeddings, self.x),
                                            perm=[1, 0, 2])  # seq_length x batch_size x emb_dim
            #self.g_processed_x = tf.transpose(tf.nn.embedding_lookup(self.g_embeddings, self.g_x),
                                            #perm=[1, 0, 2])  # seq_length x batch_size x emb_dim
            # self.g_processed_x = tf.transpose(self.g_x, perm=[1, 0])  # seq_length x batch_size      
            if self.ADDDATA == True:
                processed_class = tf.transpose(tf.nn.embedding_lookup(self.class_embeddings, self.classes),
                                            perm=[1, 0, 2])
                processed_grade = tf.transpose(tf.nn.embedding_lookup(self.grade_embeddings, self.grades),
                                            perm=[1, 0, 2])
                self.processed_context = tf.concat(axis=2, values=[processed_class, processed_grade], name='concat')

        gen_length = 20

        if self.ADDDATA == True:
            ta_emb_context = tensor_array_ops.TensorArray(
                dtype=tf.float32, size=self.sequence_length)
            ta_emb_context = ta_emb_context.unstack(self.processed_context)

        def model(self):
            def _norm(x, g=None, b=None, e=1e-5, axis=[1]):
                u = tf.reduce_mean(x, axis=axis, keep_dims=True)
                s = tf.reduce_mean(tf.square(x-u), axis=axis, keep_dims=True)
                x = (x - u) * tf.rsqrt(s + e)
                if g is not None and b is not None:
                    x = x*g + b
                return x

            def norm(x, scope, axis=[-1]):
                with tf.variable_scope(scope):
                    n_state = shape_list(x)[-1]
                    g = tf.get_variable("g", [n_state], initializer=tf.constant_initializer(1))
                    b = tf.get_variable("b", [n_state], initializer=tf.constant_initializer(0))
                    return _norm(x, g, b, axis=axis)

            def dropout(x, pdrop, train):
                if train and pdrop > 0:
                    x = tf.nn.dropout(x, 1-pdrop)
                return x

            def mask_attn_weights(w):
                n = shape_list(w)[-1]
                b = tf.matrix_band_part(tf.ones([n, n]), -1, 0)
                b = tf.reshape(b, [1, 1, n, n])
                w = w*b + -1e9*(1-b)
                return w

            def _attn(q, k, v, train=False, scale=False):
                w = tf.matmul(q, k)

                if scale:
                    n_state = shape_list(v)[-1]
                    w = w*tf.rsqrt(tf.cast(n_state, tf.float32))

                w = mask_attn_weights(w)
                w = tf.nn.softmax(w)

                w = dropout(w, attn_pdrop, train)

                a = tf.matmul(w, v)
                return a

            def split_states(x, n):
                x_shape = shape_list(x)
                m = x_shape[-1]
                new_x_shape = x_shape[:-1]+[n, m//n]
                return tf.reshape(x, new_x_shape)

            def merge_states(x):
                x_shape = shape_list(x)
                new_x_shape = x_shape[:-2]+[np.prod(x_shape[-2:])]
                return tf.reshape(x, new_x_shape)

            def split_heads(x, n, k=False):
                if k:
                    return tf.transpose(split_states(x, n), [0, 2, 3, 1])
                else:
                    return tf.transpose(split_states(x, n), [0, 2, 1, 3])

            def merge_heads(x):
                return merge_states(tf.transpose(x, [0, 2, 1, 3]))

            def conv1d(x, scope, nf, rf, w_init=tf.random_normal_initializer(stddev=0.02), b_init=tf.constant_initializer(0), pad='VALID', train=False):
                with tf.variable_scope(scope):
                    nx = shape_list(x)[-1]
                    w = tf.get_variable("w", [rf, nx, nf], initializer=w_init)
                    b = tf.get_variable("b", [nf], initializer=b_init)
                    if rf == 1: #faster 1x1 conv
                        c = tf.reshape(tf.matmul(tf.reshape(x, [-1, nx]), tf.reshape(w, [-1, nf]))+b, shape_list(x)[:-1]+[nf])
                    else: #was used to train LM
                        c = tf.nn.conv1d(x, w, stride=1, padding=pad)+b
                    return c

            def attn(x, scope, n_state, n_head, train=False, scale=False):
                assert n_state%n_head==0
                with tf.variable_scope(scope):
                    c = conv1d(x, 'c_attn', n_state*3, 1, train=train)
                    q, k, v = tf.split(c, 3, 2)
                    q = split_heads(q, n_head)
                    k = split_heads(k, n_head, k=True)
                    v = split_heads(v, n_head)
                    a = _attn(q, k, v, train=train, scale=scale)
                    a = merge_heads(a)
                    a = conv1d(a, 'c_proj', n_state, 1, train=train)
                    a = dropout(a, resid_pdrop, train)
                    return a

            def mlp(x, scope, n_state, train=False):
                with tf.variable_scope(scope):
                    nx = shape_list(x)[-1]
                    act = act_fns[afn]
                    h = act(conv1d(x, 'c_fc', n_state, 1, train=train))
                    h2 = conv1d(h, 'c_proj', nx, 1, train=train)
                    h2 = dropout(h2, resid_pdrop, train)
                    return h2

            def block(x, scope, train=True, scale=False):
                with tf.variable_scope(scope):
                nx = shape_list(x)[-1]
                a = attn(x, 'attn', nx, n_head, train=train, scale=scale)
                n = norm(x+a, 'ln_1')
                m = mlp(n, 'mlp', nx*4, train=train)
                h = norm(n+m, 'ln_2')
                return h
            
            X = self.processed_context
            h = X
            for layer in range(n_layer):
                h = block(h, 'h%d'%layer, train=train, scale=True)
            
            self.Wo = tf.Variable(self.init_matrix([self.hidden_dim, self.num_vocabulary]))
            self.bo = tf.Variable(self.init_matrix([self.num_vocabulary]))
            lm_logits = tf.matmul(h, self.Wo) + self.bo

            lm_losses = tf.nn.sparse_softmax_cross_entropy_with_logits(logits=lm_logits, labels=tf.reshape(X[:, 1:, 0], [-1]))
            lm_losses = tf.reshape(lm_losses, [shape_list(X)[0], shape_list(X)[1]-1])
        
            return lm_losses










        def _g_recurrence(i, x_t, h_tm1, gen_o, gen_x, his):
            h_t = self.g_recurrent_unit(x_t, h_tm1)  # hidden_memory_tuple
            hidden_state, c_prev = tf.unstack(h_t)
            #print('hidden_state shape %s'%hidden_state.get_shape())
            his = tf.concat([his, tf.reshape(hidden_state, [self.batch_size, 1, self.hidden_dim])], axis=1)
            #print('his %s'%his.get_shape())
            attention_outputs = self.g_att_layer(his, return_alphas=False)
            #print('attention shape %s'%attention_outputs.get_shape())
            #o_t = self.g_output_unit(h_t)  # batch x vocab , logits not prob
            o_t = self.g_output_unit(attention_outputs)  # batch x vocab , logits not prob
            #print('o_t shape %s'%o_t.get_shape())
            
            log_prob = tf.log(tf.nn.softmax(o_t))

            next_token = tf.cast(tf.reshape(tf.multinomial(log_prob, 1), [self.batch_size]), tf.int32)

            x_tp1 = tf.concat([tf.nn.embedding_lookup(self.g_embeddings, next_token), ta_emb_context.read(i)], axis=1)# batch x emb_dim
            x_tp1 = tf.reshape(x_tp1, [self.batch_size, self.emb_dim])
            gen_o = gen_o.write(i, tf.reduce_sum(tf.multiply(tf.one_hot(next_token, self.num_vocabulary, 1.0, 0.0),
                                                             tf.nn.softmax(o_t)), 1))  # [batch_size] , prob
            gen_x = gen_x.write(i, next_token)  # indices, batch_size
            return i + 1, x_tp1, h_t, gen_o, gen_x, his

        if(self.ADDDATA == True):
            _, _, _, self.gen_o, self.gen_x, _ = control_flow_ops.while_loop(
                cond=lambda i, _1, _2, _3, _4, _5: i < gen_length,
                body=_g_recurrence,
                loop_vars=(tf.constant(0, dtype=tf.int32),
                           tf.concat([tf.nn.embedding_lookup(self.g_embeddings, self.start_token), 
                                       tf.nn.embedding_lookup(self.class_embeddings, tf.constant([0] * self.batch_size, dtype=tf.int32)),
                                       tf.nn.embedding_lookup(self.grade_embeddings, tf.constant([69] * self.batch_size, dtype=tf.int32))], axis=1), 
                           self.h0, gen_o, gen_x, tf.zeros([self.batch_size, 1, self.hidden_dim])), 
                shape_invariants=(tf.TensorShape([]),
                                   tf.TensorShape([self.batch_size, None]),
                                   tf.TensorShape([2, self.batch_size, self.hidden_dim]),
                                   tf.TensorShape([]),
                                   tf.TensorShape([]),
                                   tf.TensorShape([self.batch_size, None, self.hidden_dim])
                                   ))
        else:
            _, _, _, self.gen_o, self.gen_x = control_flow_ops.while_loop(
                cond=lambda i, _1, _2, _3, _4, _5: i < gen_length,
                body=_g_recurrence,
                loop_vars=(tf.constant(0, dtype=tf.int32),
                           tf.nn.embedding_lookup(self.g_embeddings, self.start_token),  
                           self.h0, gen_o, gen_x, tf.zeros([self.batch_size, 1, self.hidden_dim])))

        self.gen_x = self.gen_x.stack()  # seq_length x batch_size
        self.gen_x = tf.transpose(self.gen_x, perm=[1, 0])  # batch_size x seq_length

        # supervised pretraining for generator
        g_predictions = tensor_array_ops.TensorArray(
            dtype=tf.float32, size=self.sequence_length,
            dynamic_size=False, infer_shape=True)

        ta_emb_x = tensor_array_ops.TensorArray(
            dtype=tf.float32, size=self.sequence_length)
        ta_emb_x = ta_emb_x.unstack(self.processed_x)

        def _pretrain_recurrence(i, x_t, h_tm1, g_predictions, his):
            h_t = self.g_recurrent_unit(x_t, h_tm1)
            hidden_state, c_prev = tf.unstack(h_t)
            his = tf.concat([his, tf.reshape(hidden_state, [self.batch_size, 1, self.hidden_dim])], axis=1)
            attention_outputs = self.g_att_layer(his, return_alphas=False)
            #o_t = self.g_output_unit(h_t)
            o_t = self.g_output_unit(attention_outputs)
            g_predictions = g_predictions.write(i, tf.nn.softmax(o_t))  # batch x vocab_size
            # x_tp1 = tf.cond(tf.cast(self.ADDDATA, tf.bool), lambda: tf.concat([ta_emb_x.read(i), ta_emb_context.read(i)], axis=1), 
            #                 lambda: ta_emb_x.read(i))
            x_tp1 = tf.concat([ta_emb_x.read(i), ta_emb_context.read(i)], axis=1)
            x_tp1 = tf.reshape(x_tp1, [self.batch_size, self.emb_dim])
            return i + 1, x_tp1, h_t, g_predictions, his

        # if(self.ADDDATA == True):    
        #     _, _, _, self.g_predictions = control_flow_ops.while_loop(
        #         cond=lambda i, _1, _2, _3, _4: i < self.sequence_length,
        #         body=_pretrain_recurrence,
        #         loop_vars=(tf.constant(0, dtype=tf.int32),
        #                    tf.concat([tf.nn.embedding_lookup(self.g_embeddings, self.start_token), 
        #                    tf.nn.embedding_lookup(self.class_embeddings, tf.constant([0] * self.batch_size, dtype=tf.int32)),
        #                    tf.nn.embedding_lookup(self.grade_embeddings, tf.constant([69] * self.batch_size, dtype=tf.int32))], axis=1),  
        #                    self.h0, g_predictions, tf.zeros([self.batch_size, 1, self.hidden_dim])))
        if(self.ADDDATA == True):
            _, _, _, self.g_predictions, _ = control_flow_ops.while_loop(
                cond=lambda i, _1, _2, _3, _4: i < self.sequence_length,
                body=_pretrain_recurrence,
                loop_vars=(tf.constant(0, dtype=tf.int32),
                           tf.concat([tf.nn.embedding_lookup(self.g_embeddings, self.start_token), 
                                       tf.nn.embedding_lookup(self.class_embeddings, tf.constant([0] * self.batch_size, dtype=tf.int32)),
                                       tf.nn.embedding_lookup(self.grade_embeddings, tf.constant([69] * self.batch_size, dtype=tf.int32))], axis=1), 
                           self.h0, g_predictions, tf.zeros([self.batch_size, 1, self.hidden_dim])), 
                shape_invariants=(tf.TensorShape([]),
                                   tf.TensorShape([self.batch_size, None]),
                                   tf.TensorShape([2, self.batch_size, self.hidden_dim]),
                                   tf.TensorShape([]),
                                   tf.TensorShape([self.batch_size, None, self.hidden_dim])
                                   ))        
        else:
            _, _, _, self.g_predictions = control_flow_ops.while_loop(
                cond=lambda i, _1, _2, _3, _4: i < self.sequence_length,
                body=_pretrain_recurrence,
                loop_vars=(tf.constant(0, dtype=tf.int32),
                           tf.nn.embedding_lookup(self.g_embeddings, self.start_token), 
                           self.h0, g_predictions, tf.zeros([self.batch_size, 1, self.hidden_dim])))

        self.g_predictions = tf.transpose(self.g_predictions.stack(),
                                          perm=[1, 0, 2])  # batch_size x seq_length x vocab_size

        # pretraining loss
        self.pretrain_loss = -tf.reduce_sum(
            tf.one_hot(tf.to_int32(tf.reshape(self.x, [-1])), self.num_vocabulary, 1.0, 0.0) * tf.log(
                tf.clip_by_value(tf.reshape(self.g_predictions, [-1, self.num_vocabulary]), 1e-20, 1.0)
            )
        ) / (self.sequence_length * self.batch_size)

        # training updates
        pretrain_opt = self.g_optimizer(self.learning_rate)

        self.pretrain_grad, _ = tf.clip_by_global_norm(tf.gradients(self.pretrain_loss, self.g_params), self.grad_clip)
        self.pretrain_updates = pretrain_opt.apply_gradients(zip(self.pretrain_grad, self.g_params))

        #######################################################################################################
        #  Unsupervised Training
        #######################################################################################################
        self.g_loss = -tf.reduce_sum(
            tf.reduce_sum(
                tf.one_hot(tf.to_int32(tf.reshape(self.x, [-1])), self.num_vocabulary, 1.0, 0.0) * tf.log(
                    tf.clip_by_value(tf.reshape(self.g_predictions, [-1, self.num_vocabulary]), 1e-20, 1.0)
                ), 1) * tf.reshape(self.rewards, [-1])
        )

        g_opt = self.g_optimizer(self.learning_rate)

        self.g_grad, _ = tf.clip_by_global_norm(tf.gradients(self.g_loss, self.g_params), self.grad_clip)
        self.g_updates = g_opt.apply_gradients(zip(self.g_grad, self.g_params))

    def generate(self, sess, grades, classes):
        outputs = sess.run([self.gen_x], feed_dict={self.grades: grades, self.classes: classes})
        return outputs

    def pretrain_step(self, sess, x, grades, classes):
        if(self.ADDDATA == True):
            outputs = sess.run([self.pretrain_updates, self.pretrain_loss], feed_dict={self.x: x, self.grades: grades, self.classes: classes})
        else:
            outputs = sess.run([self.pretrain_updates, self.pretrain_loss], feed_dict={self.x: x})
        return outputs

    def init_matrix(self, shape):
        return tf.random_normal(shape, stddev=0.1)

    def init_vector(self, shape):
        return tf.zeros(shape)

    def g_optimizer(self, *args, **kwargs):
        return tf.train.AdamOptimizer(*args, **kwargs)

        # Compute the similarity between minibatch examples and all embeddings.
        # We use the cosine distance:
