from gym.envs.registration import register

register(
    id='gym_examples/Albert-v0',
    entry_point='gym_examples.envs:AlbertEnv',
    max_episode_steps=2400,
)