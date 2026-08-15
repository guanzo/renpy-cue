# Video fixture for the Phase 3 (hard-tier) testcases.
#
# The mod does not play video itself -- it observes a Movie the host game
# shows. This image registers a tiny decodable WebM (cuevideo.webm, VP8, 2s)
# on the "movie" channel so a testcase can `scene cuevid` and drive the real
# Movie -> wrap -> top-layer-detect -> channel-discovery path.
#
# loop=True keeps the short clip alive across the testcase's pauses.

image cuevid = Movie(play="cuevideo.webm", channel="movie", loop=True)
