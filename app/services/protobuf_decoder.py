# load_proto.py

from google.protobuf import descriptor_pb2
from google.protobuf import descriptor_pool
from google.protobuf.message_factory import GetMessageClass
import os


class ProtoLoader:
    """
    Loads compiled .desc protobuf dynamically and returns message classes.
    """

    def __init__(self):
        self.pool = descriptor_pool.Default()

    # ------------------------------------------------------
    def load_proto_file(self, proto_path: str):
        """
        Load a compiled descriptor_set (.desc file)
        """
        if not os.path.exists(proto_path):
            raise FileNotFoundError(f"Descriptor file not found: {proto_path}")

        fdset = descriptor_pb2.FileDescriptorSet()

        with open(proto_path, "rb") as f:
            fdset.ParseFromString(f.read())

        for fd_proto in fdset.file:
            self.pool.Add(fd_proto)

        return True

    # ------------------------------------------------------
    def get_message_class(self, full_name: str):
        """
        Returns Python message class dynamically.
        """
        descriptor = self.pool.FindMessageTypeByName(full_name)
        return GetMessageClass(descriptor)


# ---------------------------------------------------------
# DEMO
# ---------------------------------------------------------
if __name__ == "__main__":
    loader = ProtoLoader()

    loader.load_proto_file("market.desc")

    FeedResponse = loader.get_message_class(
        "com.upstox.marketdatafeeder.rpc.proto.FeedResponse"
    )

    print("Loaded:", FeedResponse)
